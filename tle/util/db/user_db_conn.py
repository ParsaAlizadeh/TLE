from enum import IntEnum
from collections import namedtuple
import psycopg2
import psycopg2.extras

from discord.ext import commands

from tle.util import codeforces_api as cf

_DEFAULT_VC_RATING = 1500

class Gitgud(IntEnum):
    GOTGUD = 0
    GITGUD = 1
    NOGUD = 2
    FORCED_NOGUD = 3

class Duel(IntEnum):
    PENDING = 0
    DECLINED = 1
    WITHDRAWN = 2
    EXPIRED = 3
    ONGOING = 4
    COMPLETE = 5
    INVALID = 6

class Winner(IntEnum):
    DRAW = 0
    CHALLENGER = 1
    CHALLENGEE = 2

class DuelType(IntEnum):
    UNOFFICIAL = 0
    OFFICIAL = 1
class RatedVC(IntEnum):
    ONGOING = 0
    FINISHED = 1


class UserDbError(commands.CommandError):
    pass


class DatabaseDisabledError(UserDbError):
    pass


class DummyUserDbConn:
    def __getattribute__(self, item):
        raise DatabaseDisabledError


class UniqueConstraintFailed(UserDbError):
    pass


def namedtuple_factory(cursor, row):
    """Returns sqlite rows as named tuples."""
    fields = [col[0] for col in cursor.description if col[0].isidentifier()]
    Row = namedtuple("Row", fields)
    return Row(*row)


class UserDbConn:
    def __init__(self, db_url):
        self.db_url = db_url
        self.conn = psycopg2.connect(db_url)
        self.conn.rollback()
        self.create_tables()

    def rollback(self):
        self.conn.rollback()
    
    def reconnect(self):
        self.conn = psycopg2.connect(self.db_url)

    def create_tables(self):
        cur = self.conn.cursor()
        cur.execute(
            'CREATE TABLE IF NOT EXISTS user_handle ('
            'user_id     TEXT,'
            'guild_id    TEXT,'
            'handle      TEXT,'
            'active      INTEGER,'
            'PRIMARY KEY (user_id, guild_id)'
            ');'
        )
        cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_user_handle_guild_handle '
                          'ON user_handle (guild_id, handle)')
        cur.execute(
            'CREATE TABLE IF NOT EXISTS cf_user_cache ('
            'handle              TEXT PRIMARY KEY,'
            'first_name          TEXT,'
            'last_name           TEXT,'
            'country             TEXT,'
            'city                TEXT,'
            'organization        TEXT,'
            'contribution        INTEGER,'
            'rating              INTEGER,'
            'maxRating           INTEGER,'
            'last_online_time    INTEGER,'
            'registration_time   INTEGER,'
            'friend_of_count     INTEGER,'
            'title_photo         TEXT'
            ');'
        )
        # TODO: Make duel tables guild-aware.
        cur.execute('''
            CREATE TABLE IF NOT EXISTS duelist (
                "user_id"	BIGINT PRIMARY KEY NOT NULL,
                "rating"	INTEGER NOT NULL
            );
        ''')

        cur.execute(''' ALTER TABLE IF EXISTS duel ALTER COLUMN "challenger" TYPE BIGINT; ''')
        cur.execute(''' ALTER TABLE IF EXISTS duel ALTER COLUMN "challengee" TYPE BIGINT; ''')
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS duel (
                "id"	        SERIAL PRIMARY KEY,
                "challenger"	BIGINT NOT NULL,
                "challengee"	BIGINT NOT NULL,
                "issue_time"	REAL NOT NULL,
                "start_time"	REAL,
                "finish_time"	REAL,
                "problem_name"	TEXT,
                "contest_id"	INTEGER,
                "p_index"	    TEXT,
                "status"	    INTEGER,
                "winner"	    INTEGER,
                "type"		    INTEGER
            );
        ''')
        

        cur.execute('''
            CREATE TABLE IF NOT EXISTS "challenge" (
                "id"	        SERIAL PRIMARY KEY,
                "user_id"	    TEXT NOT NULL,
                "issue_time"	REAL NOT NULL,
                "finish_time"	REAL,
                "problem_name"	TEXT NOT NULL,
                "contest_id"	INTEGER NOT NULL,
                "p_index"	    TEXT NOT NULL,
                "rating_delta"	INTEGER NOT NULL,
                "status"	    INTEGER NOT NULL
            );
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS "user_challenge" (
                "user_id"	            TEXT,
                "active_challenge_id"	INTEGER,
                "issue_time"	        REAL,
                "score"	INTEGER         NOT NULL,
                "num_completed"	        INTEGER NOT NULL,
                "num_skipped"	        INTEGER NOT NULL,
                PRIMARY KEY("user_id")
            );
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS reminder (
                guild_id        TEXT PRIMARY KEY,
                channel_id      TEXT,
                role_id         TEXT,
                before          TEXT
            );
        ''')
        cur.execute(
            'CREATE TABLE IF NOT EXISTS starboard ('
            'guild_id     TEXT PRIMARY KEY,'
            'channel_id   TEXT'
            ');'
        )
        cur.execute(
            'CREATE TABLE IF NOT EXISTS starboard_message ('
            'original_msg_id    TEXT PRIMARY KEY,'
            'starboard_msg_id   TEXT,'
            'guild_id           TEXT'
            ');'
        )
        cur.execute(
            'CREATE TABLE IF NOT EXISTS rankup ('
            'guild_id     TEXT PRIMARY KEY,'
            'channel_id   TEXT'
            ');'
        )
        cur.execute(
            'CREATE TABLE IF NOT EXISTS auto_role_update ('
            'guild_id     TEXT PRIMARY KEY'
            ');'
        )

        # Rated VCs stuff:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS "rated_vcs" (
                "id"	         SERIAL PRIMARY KEY,
                "contest_id"     INTEGER NOT NULL,
                "start_time"     REAL,
                "finish_time"    REAL,
                "status"         INTEGER,
                "guild_id"       TEXT
            );
        ''')

        # TODO: Do we need to explicitly specify the fk constraint or just depend on the middleware%s
        cur.execute('''
            CREATE TABLE IF NOT EXISTS "rated_vc_users" (
                "vc_id"	         INTEGER,
                "user_id"        TEXT NOT NULL,
                "rating"         INTEGER,

                CONSTRAINT fk_vc
                    FOREIGN KEY (vc_id)
                    REFERENCES rated_vcs(id),

                PRIMARY KEY(vc_id, user_id)
            );
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS rated_vc_settings (
                guild_id TEXT PRIMARY KEY,
                channel_id TEXT
            );
        ''')

        # set current id for serial columns
        cur.execute('''
            SELECT setval(pg_get_serial_sequence('duel', 'id'), (SELECT MAX(id) FROM duel) + 1);
        ''')

        cur.execute('''
            SELECT setval(pg_get_serial_sequence('challenge', 'id'), (SELECT MAX(id) FROM challenge) + 1);
        ''')

        cur.execute('''
            SELECT setval(pg_get_serial_sequence('rated_vcs', 'id'), (SELECT MAX(id) FROM rated_vcs) + 1);
        ''')

        self.conn.commit()


    # Helper functions.

    def _insert_one(self, table: str, columns, values: tuple):
        n = len(values)
        first_col = columns[0]
        rest_cols = map(lambda s: '{} = EXCLUDED.{},'.format(s), columns[1:])
        query = '''
            INSERT INTO {} ({}) VALUES ({})
            ON CONFLICT ({}) 
            DO UPDATE SET 
            {}
        '''.format(table, ', '.join(columns), ', '.join(['%s'] * n), first_col, rest_cols)
        query = query[:-1] + ';'
        cur = self.conn.cursor()
        cur.execute(query, values)
        rc = cur.rowcount
        self.conn.commit()
        return rc

    def _insert_many(self, table: str, columns, values: list):
        n = len(values)
        first_col = columns[0]
        rest_cols = map(lambda s: '{} = EXCLUDED.{},'.format(s), columns[1:])
        query = '''
            INSERT INTO {} ({}) VALUES ({})
            ON CONFLICT ({}) 
            DO UPDATE SET 
            {}
        '''.format(table, ', '.join(columns), ', '.join(['%s'] * n), first_col, rest_cols)
        query = query[:-1] + ';'
        cur = self.conn.cursor()
        cur.executemany(query, values)
        rc = cur.rowcount
        self.conn.commit()
        return rc

    def _fetchone(self, query: str, params=None, cursor_factory=None):
        if cursor_factory:
            cur = self.conn.cursor(cursor_factory = cursor_factory)
        else:
            cur = self.conn.cursor()
        cur.execute(query, params)
        return cur.fetchone()

    def _fetchall(self, query: str, params=None, cursor_factory=None):
        if cursor_factory:
            cur = self.conn.cursor(cursor_factory = cursor_factory)
        else:
            cur = self.conn.cursor()
        cur.execute(query, params)
        return cur.fetchall()

    def new_challenge(self, user_id, issue_time, prob, delta):
        query1 = '''
            INSERT INTO challenge
            (user_id, issue_time, problem_name, contest_id, p_index, rating_delta, status)
            VALUES
            (CAST(%s AS TEXT), %s, %s, %s, CAST(%s AS TEXT), %s, 1) 
            RETURNING id;
        '''
        query2 = '''
            INSERT INTO user_challenge (user_id, score, num_completed, num_skipped)
            VALUES (CAST(%s AS TEXT), 0, 0, 0)
            ON CONFLICT DO NOTHING;
        '''
        query3 = '''
            UPDATE user_challenge SET active_challenge_id = %s, issue_time = %s
            WHERE user_id = CAST(%s AS TEXT) AND active_challenge_id IS NULL;
        '''
        cur = self.conn.cursor()
        cur.execute(query1, (user_id, issue_time, prob.name, prob.contestId, prob.index, delta))
        last_id, rc = cur.fetchone()[0], cur.rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        cur.execute(query2, (user_id,))
        cur.execute(query3, (last_id, issue_time, user_id))
        if cur.rowcount != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return 1

    def check_challenge(self, user_id):
        query1 = '''
            SELECT active_challenge_id, issue_time FROM user_challenge
            WHERE user_id = CAST(%s AS TEXT);
        '''
        cur = self.conn.cursor()
        cur.execute(query1, (user_id,))
        res = cur.fetchone()
        if res is None:
            return None
        c_id, issue_time = res
        query2 = '''
            SELECT problem_name, contest_id, p_index, rating_delta FROM challenge
            WHERE id = %s;
        '''
        cur.execute(query2, (c_id,))
        res = cur.fetchone()
        print(res)
        if res is None:
            return None
        return c_id, issue_time, res[0], res[1], res[2], res[3]

    def get_gudgitters(self):
        query = '''
            SELECT user_id, score FROM user_challenge;
        '''
        cur = self.conn.cursor()
        cur.execute(query)
        return cur.fetchall()

    def howgud(self, user_id):
        query = '''
            SELECT rating_delta FROM challenge WHERE user_id = CAST(%s AS TEXT) AND finish_time IS NOT NULL;
        '''
        cur = self.conn.cursor()
        cur.execute(query, (user_id,))
        return cur.fetchall()

    def get_noguds(self, user_id):
        query = ('SELECT problem_name '
                 'FROM challenge '
                 f'WHERE user_id = CAST(%s AS TEXT) AND status = {Gitgud.NOGUD};')
        cur = self.conn.cursor()
        cur.execute(query, (user_id,))
        return {name for name, in cur.fetchall()}

    def gitlog(self, user_id):
        query = f'''
            SELECT issue_time, finish_time, problem_name, contest_id, p_index, rating_delta, status
            FROM challenge WHERE user_id = CAST(%s AS TEXT) AND status != {Gitgud.FORCED_NOGUD} ORDER BY issue_time DESC;
        '''
        cur = self.conn.cursor()
        cur.execute(query, (user_id,))
        return cur.fetchall()

    def complete_challenge(self, user_id, challenge_id, finish_time, delta):
        query1 = f'''
            UPDATE challenge SET finish_time = %s, status = {Gitgud.GOTGUD}
            WHERE id = %s AND status = {Gitgud.GITGUD};
        '''
        query2 = '''
            UPDATE user_challenge SET score = score + %s, num_completed = num_completed + 1,
            active_challenge_id = NULL, issue_time = NULL
            WHERE user_id = CAST(%s AS TEXT) AND active_challenge_id = %s;
        '''
        cur = self.conn.cursor()
        cur.execute(query1, (finish_time, challenge_id))
        rc = cur.rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        cur.execute(query2, (delta, user_id, challenge_id))
        rc = cur.rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return 1

    def skip_challenge(self, user_id, challenge_id, status):
        query1 = '''
            UPDATE user_challenge SET active_challenge_id = NULL, issue_time = NULL
            WHERE user_id = CAST(%s AS TEXT) AND active_challenge_id = %s;
        '''
        query2 = f'''
            UPDATE challenge SET status = %s WHERE id = %s AND status = {Gitgud.GITGUD};
        '''
        cur = self.conn.cursor()
        cur.execute(query1, (user_id, challenge_id))
        rc = cur.rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        cur.execute(query2, (status, challenge_id))
        rc = cur.rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return 1

    def cache_cf_user(self, user):
        query = ('INSERT INTO cf_user_cache '
                 '(handle, first_name, last_name, country, city, organization, contribution, '
                 ' rating, maxRating, last_online_time, registration_time, friend_of_count, title_photo) '
                 'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) '
                 'ON CONFLICT (handle) '
                 'DO UPDATE SET '
                 'first_name = EXCLUDED.first_name,'
                 'last_name = EXCLUDED.last_name,'
                 'country = EXCLUDED.country,'
                 'city = EXCLUDED.city,'
                 'organization = EXCLUDED.organization,'
                 'contribution = EXCLUDED.contribution,'
                 'rating = EXCLUDED.rating,'
                 'maxRating = EXCLUDED.maxRating,'
                 'last_online_time = EXCLUDED.last_online_time,'
                 'registration_time = EXCLUDED.registration_time,'
                 'friend_of_count = EXCLUDED.friend_of_count,'
                 'title_photo = EXCLUDED.title_photo;'
                 )
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, user)
            return cur.rowcount

    def fetch_cf_user(self, handle):
        query = ('SELECT handle, first_name, last_name, country, city, organization, contribution, '
                 '    rating, maxRating, last_online_time, registration_time, friend_of_count, title_photo '
                 'FROM cf_user_cache '
                 'WHERE UPPER(handle) = UPPER(%s);')
        cur = self.conn.cursor()
        cur.execute(query, (handle,))
        user = cur.fetchone()
        return cf.User._make(user) if user else None

    def set_handle(self, user_id, guild_id, handle):
        query = ('SELECT user_id '
                 'FROM user_handle '
                 'WHERE guild_id = CAST(%s AS TEXT) AND handle = %s;')
        cur = self.conn.cursor()
        cur.execute(query, (guild_id, handle))
        existing = cur.fetchone()
        if existing and int(existing[0]) != user_id:
            raise UniqueConstraintFailed

        query = ('INSERT INTO user_handle '
                 '(user_id, guild_id, handle, active) '
                 'VALUES (CAST(%s AS TEXT), CAST(%s AS TEXT), %s, 1) '
                 'ON CONFLICT (user_id, guild_id) '
                 'DO UPDATE SET '
                 'handle = EXCLUDED.handle,'
                 'active = EXCLUDED.active;')
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (user_id, guild_id, handle))
            return cur.rowcount

    def set_inactive(self, guild_id_user_id_pairs):
        query = ('UPDATE user_handle '
                 'SET active = 0 '
                 'WHERE guild_id = CAST(%s AS TEXT) AND user_id = CAST(%s AS TEXT);')
        with self.conn:
            cur = self.conn.cursor()
            cur.executemany(query, guild_id_user_id_pairs)
            return cur.rowcount

    def get_handle(self, user_id, guild_id):
        query = ('SELECT handle '
                 'FROM user_handle '
                 'WHERE user_id = CAST(%s AS TEXT) AND guild_id = CAST(%s AS TEXT);')
        cur = self.conn.cursor()
        cur.execute(query, (user_id, guild_id))
        res = cur.fetchone()
        return res[0] if res else None

    def get_user_id(self, handle, guild_id):
        query = ('SELECT user_id '
                 'FROM user_handle '
                 'WHERE UPPER(handle) = UPPER(%s) AND guild_id = CAST(%s AS TEXT) AND active = 1;')
        cur = self.conn.cursor()
        cur.execute(query, (handle, guild_id))
        res = cur.fetchone()
        return int(res[0]) if res else None

    def remove_handle(self, user_id, guild_id):
        query = ('DELETE FROM user_handle '
                 'WHERE user_id = CAST(%s AS TEXT) AND guild_id = CAST(%s AS TEXT);')
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (user_id, guild_id))
            return cur.rowcount

    def get_handles_for_guild(self, guild_id):
        query = ('SELECT user_id, handle '
                 'FROM user_handle '
                 'WHERE guild_id = CAST(%s AS TEXT) AND active = 1;')
        cur = self.conn.cursor()
        cur.execute(query, (guild_id,))
        res = cur.fetchall()
        return [(int(user_id), handle) for user_id, handle in res]

    def get_cf_users_for_guild(self, guild_id):
        query = ('SELECT u.user_id, c.handle, c.first_name, c.last_name, c.country, c.city, '
                 '    c.organization, c.contribution, c.rating, c.maxRating, c.last_online_time, '
                 '    c.registration_time, c.friend_of_count, c.title_photo '
                 'FROM user_handle AS u '
                 'LEFT JOIN cf_user_cache AS c '
                 'ON u.handle = c.handle '
                 'WHERE u.guild_id = CAST(%s AS TEXT) AND u.active = 1;')
        cur = self.conn.cursor()
        cur.execute(query, (guild_id,))
        res = cur.fetchall()
        return [(int(t[0]), cf.User._make(t[1:])) for t in res]

    def get_reminder_settings(self, guild_id):
        query = '''
            SELECT channel_id, role_id, before
            FROM reminder
            WHERE guild_id = CAST(%s AS TEXT);
        '''
        cur = self.conn.cursor()
        cur.execute(query, (guild_id,))
        return cur.fetchone()

    def set_reminder_settings(self, guild_id, channel_id, role_id, before):
        query = '''
            INSERT INTO reminder (guild_id, channel_id, role_id, before)
            VALUES (CAST(%s AS TEXT), %s, %s, %s) 
            ON CONFLICT (guild_id) 
            DO UPDATE SET 
            channel_id = EXCLUDED.channel_id,
            role_id = EXCLUDED.role_id,
            before = EXCLUDED.before;
        '''
        cur = self.conn.cursor()
        cur.execute(query, (guild_id, channel_id, role_id, before))
        self.conn.commit()

    def clear_reminder_settings(self, guild_id):
        query = '''DELETE FROM reminder WHERE guild_id = CAST(%s AS TEXT);'''
        cur = self.conn.cursor()
        cur.execute(query, (guild_id,))
        self.conn.commit()

    def get_starboard(self, guild_id):
        query = ('SELECT channel_id '
                 'FROM starboard '
                 'WHERE guild_id = CAST(%s AS TEXT)')
        cur = self.conn.cursor()
        cur.execute(query, (guild_id,))
        return cur.fetchone()

    def set_starboard(self, guild_id, channel_id):
        query = ('INSERT INTO starboard '
                 '(guild_id, channel_id) '
                 'VALUES (CAST(%s AS TEXT), %s)'
                 'ON CONFLICT (guild_id) '
                 'DO UPDATE SET '
                 'channel_id = EXCLUDED.channel_id;')
        cur = self.conn.cursor()
        cur.execute(query, (guild_id, channel_id))
        self.conn.commit()

    def clear_starboard(self, guild_id):
        query = ('DELETE FROM starboard '
                 'WHERE guild_id = CAST(%s AS TEXT);')
        cur = self.conn.cursor()
        cur.execute(query, (guild_id,))
        self.conn.commit()

    def add_starboard_message(self, original_msg_id, starboard_msg_id, guild_id):
        query = ('INSERT INTO starboard_message '
                 '(original_msg_id, starboard_msg_id, guild_id) '
                 'VALUES (%s, %s, CAST(%s AS TEXT));')
        cur = self.conn.cursor()
        cur.execute(query, (original_msg_id, starboard_msg_id, guild_id))
        self.conn.commit()

    def check_exists_starboard_message(self, original_msg_id):
        query = ('SELECT 1 '
                 'FROM starboard_message '
                 'WHERE original_msg_id = %s;')
        cur = self.conn.cursor()
        cur.execute(query, (original_msg_id,))
        res = cur.fetchone()
        return res is not None

    def remove_starboard_message(self, *, original_msg_id=None, starboard_msg_id=None):
        assert (original_msg_id is None) ^ (starboard_msg_id is None)
        cur = self.conn.cursor()
        if original_msg_id is not None:
            query = ('DELETE FROM starboard_message '
                     'WHERE original_msg_id = %s;')
            cur.execute(query, (original_msg_id,))
        else:
            query = ('DELETE FROM starboard_message '
                     'WHERE starboard_msg_id = %s;')
            cur.execute(query, (starboard_msg_id,))
        rc = cur.rowcount
        self.conn.commit()
        return rc

    def clear_starboard_messages_for_guild(self, guild_id):
        query = ('DELETE FROM starboard_message '
                 'WHERE guild_id = CAST(%s AS TEXT);')
        cur = self.conn.cursor()
        cur.execute(query, (guild_id,))
        rc = cur.rowcount
        self.conn.commit()
        return rc

    def check_duel_challenge(self, userid):
        query = f'''
            SELECT id FROM duel
            WHERE (challengee = %s OR challenger = %s) AND (status = {Duel.ONGOING} OR status = {Duel.PENDING});
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid, userid))
        return cur.fetchone()

    def check_duel_accept(self, challengee):
        query = f'''
            SELECT id, challenger, problem_name FROM duel
            WHERE challengee = %s AND status = {Duel.PENDING};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (challengee,))
        return cur.fetchone()

    def check_duel_decline(self, challengee):
        query = f'''
            SELECT id, challenger FROM duel
            WHERE challengee = %s AND status = {Duel.PENDING};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (challengee,))
        return cur.fetchone()

    def check_duel_withdraw(self, challenger):
        query = f'''
            SELECT id, challengee FROM duel
            WHERE challenger = %s AND status = {Duel.PENDING};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (challenger,))
        cur.execute(query, (challenger,))
        return cur.fetchone()

    def check_duel_draw(self, userid):
        query = f'''
            SELECT id, challenger, challengee, start_time, type FROM duel
            WHERE (challenger = %s OR challengee = %s) AND status = {Duel.ONGOING};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid, userid))
        return cur.fetchone()

    def check_duel_complete(self, userid):
        query = f'''
            SELECT id, challenger, challengee, start_time, problem_name, contest_id, p_index, type FROM duel
            WHERE (challenger = %s OR challengee = %s) AND status = {Duel.ONGOING};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid, userid))
        return cur.fetchone()

    def create_duel(self, challenger, challengee, issue_time, prob, dtype):
        query = f'''
            INSERT INTO duel (challenger, challengee, issue_time, problem_name, contest_id, p_index, status, type) VALUES (%s, %s, %s, %s, %s, CAST(%s AS TEXT), {Duel.PENDING}, %s);
        '''
        cur = self.conn.cursor()
        cur.execute(query, (challenger, challengee, issue_time, prob.name, prob.contestId, prob.index, dtype))
        duelid = cur.lastrowid
        self.conn.commit()
        return duelid

    def cancel_duel(self, duelid, status):
        query = f'''
            UPDATE duel SET status = %s WHERE id = %s AND status = {Duel.PENDING};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (status, duelid))
        rc = cur.rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return rc

    def invalidate_duel(self, duelid):
        query = f'''
            UPDATE duel SET status = {Duel.INVALID} WHERE id = %s AND status = {Duel.ONGOING};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (duelid,))
        rc = cur.rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return rc

    def start_duel(self, duelid, start_time):
        query = f'''
            UPDATE duel SET start_time = %s, status = {Duel.ONGOING} WHERE id = %s AND status = {Duel.PENDING};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (start_time, duelid))
        rc = cur.rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return rc

    def complete_duel(self, duelid, winner, finish_time, winner_id = -1, loser_id = -1, delta = 0, dtype = DuelType.OFFICIAL):
        query = f'''
            UPDATE duel SET status = {Duel.COMPLETE}, finish_time = %s, winner = %s WHERE id = %s AND status = {Duel.ONGOING};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (finish_time, winner, duelid))
        rc = cur.rowcount
        if rc != 1:
            self.conn.rollback()
            return 0

        if dtype == DuelType.OFFICIAL:
            self.update_duel_rating(winner_id, +delta)
            self.update_duel_rating(loser_id, -delta)

        self.conn.commit()
        return 1

    def update_duel_rating(self, userid, delta):
        query = '''
            UPDATE duelist SET rating = rating + %s WHERE user_id = %s;
        '''
        cur = self.conn.cursor()
        cur.execute(query, (delta, userid))
        rc = cur.rowcount
        self.conn.commit()
        return rc

    def get_duel_wins(self, userid):
        query = f'''
            SELECT start_time, finish_time, problem_name, challenger, challengee FROM duel
            WHERE ((challenger = %s AND winner = {Winner.CHALLENGER}) OR (challengee = %s AND winner = {Winner.CHALLENGEE})) AND status = {Duel.COMPLETE};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid, userid))
        return cur.fetchall()

    def get_duels(self, userid):
        query = f'''
            SELECT id, start_time, finish_time, problem_name, challenger, challengee, winner FROM duel WHERE (challengee = %s OR challenger = %s) AND status = {Duel.COMPLETE} ORDER BY start_time DESC;
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid, userid))
        return cur.fetchall()

    def get_duel_problem_names(self, userid):
        query = f'''
            SELECT problem_name FROM duel WHERE (challengee = %s OR challenger = %s) AND (status = {Duel.COMPLETE} OR status = {Duel.INVALID});
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid, userid))
        return cur.fetchall()

    def get_pair_duels(self, userid1, userid2):
        query = f'''
            SELECT id, start_time, finish_time, problem_name, challenger, challengee, winner FROM duel
            WHERE ((challenger = %s AND challengee = %s) OR (challenger = %s AND challengee = %s)) AND status = {Duel.COMPLETE} ORDER BY start_time DESC;
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid1, userid2, userid2, userid1))
        return cur.fetchall()

    def get_recent_duels(self):
        query = f'''
            SELECT id, start_time, finish_time, problem_name, challenger, challengee, winner FROM duel WHERE status = {Duel.COMPLETE} ORDER BY start_time DESC LIMIT 7;
        '''
        cur = self.conn.cursor()
        cur.execute(query)
        return cur.fetchall()

    def get_ongoing_duels(self):
        query = f'''
            SELECT start_time, problem_name, challenger, challengee FROM duel
            WHERE status = {Duel.ONGOING} ORDER BY start_time DESC;
        '''
        cur = self.conn.cursor()
        cur.execute(query)
        return cur.fetchall()

    def get_num_duel_completed(self, userid):
        query = f'''
            SELECT COUNT(*) FROM duel WHERE (challengee = %s OR challenger = %s) AND status = {Duel.COMPLETE};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid, userid))
        return cur.fetchone()[0]

    def get_num_duel_draws(self, userid):
        query = f'''
            SELECT COUNT(*) FROM duel WHERE (challengee = %s OR challenger = %s) AND winner = {Winner.DRAW};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid, userid))
        return cur.fetchone()[0]

    def get_num_duel_losses(self, userid):
        query = f'''
            SELECT COUNT(*) FROM duel
            WHERE ((challengee = %s AND winner = {Winner.CHALLENGER}) OR (challenger = %s AND winner = {Winner.CHALLENGEE})) AND status = {Duel.COMPLETE};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid, userid))
        return cur.fetchone()[0]

    def get_num_duel_declined(self, userid):
        query = f'''
            SELECT COUNT(*) FROM duel WHERE challengee = %s AND status = {Duel.DECLINED};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid,))
        return cur.fetchone()[0]

    def get_num_duel_rdeclined(self, userid):
        query = f'''
            SELECT COUNT(*) FROM duel WHERE challenger = %s AND status = {Duel.DECLINED};
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid,))
        return cur.fetchone()[0]

    def get_duel_rating(self, userid):
        query = '''
            SELECT rating FROM duelist WHERE user_id = %s;
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid,))
        return cur.fetchone()[0]

    def is_duelist(self, userid):
        query = '''
            SELECT 1 FROM duelist WHERE user_id = %s;
        '''
        cur = self.conn.cursor()
        cur.execute(query, (userid,))
        return cur.fetchone()

    def register_duelist(self, userid):
        query = '''
            INSERT INTO duelist (user_id, rating)
            VALUES (%s, 1500)
            ON CONFLICT DO NOTHING;
        '''
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (userid,))
            return cur.rowcount

    def get_duelists(self):
        query = '''
            SELECT user_id, rating FROM duelist ORDER BY rating DESC;
        '''
        cur = self.conn.cursor()
        cur.execute(query)
        return cur.fetchall()

    def get_complete_official_duels(self):
        query = f'''
            SELECT challenger, challengee, winner, finish_time FROM duel WHERE status={Duel.COMPLETE}
            AND type={DuelType.OFFICIAL} ORDER BY finish_time ASC;
        '''
        cur = self.conn.cursor()
        cur.execute(query)
        return cur.fetchall()

    def get_rankup_channel(self, guild_id):
        query = ('SELECT channel_id '
                 'FROM rankup '
                 'WHERE guild_id = CAST (%s AS TEXT);')
        cur = self.conn.cursor()
        cur.execute(query, (guild_id,))
        channel_id = cur.fetchone()
        return int(channel_id[0]) if channel_id else None

    def set_rankup_channel(self, guild_id, channel_id):
        query = ('INSERT INTO rankup '
                 '(guild_id, channel_id) '
                 'VALUES (CAST (%s AS TEXT), %s)'
                 'ON CONFLICT (guild_id) '
                 'DO UPDATE SET '
                 'channel_id = EXCLUDED.channel_id;')
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (guild_id, channel_id))

    def clear_rankup_channel(self, guild_id):
        query = ('DELETE FROM rankup '
                 'WHERE guild_id = CAST(%s AS TEXT);')
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (guild_id,))
            return cur.rowcount

    def enable_auto_role_update(self, guild_id):
        query = ('INSERT INTO auto_role_update '
                 '(guild_id) '
                 'VALUES (CAST(%s AS TEXT)) '
                 'ON CONFLICT DO NOTHING;')
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (guild_id,))
            return cur.rowcount

    def disable_auto_role_update(self, guild_id):
        query = ('DELETE FROM auto_role_update '
                 'WHERE guild_id = CAST(%s AS TEXT);')
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (guild_id,))
            return cur.rowcount

    def has_auto_role_update_enabled(self, guild_id):
        query = ('SELECT 1 '
                 'FROM auto_role_update '
                 'WHERE guild_id = CAST(%s AS INTEGER);')
        cur = self.conn.cursor()
        cur.execute(query, (guild_id,))
        return cur.fetchone() is not None

    def update_status(self, active_ids: list):
        # TODO: Deal with the whole status thing.
        if not active_ids: return 0
        placeholders = ', '.join(['CAST(%s AS TEXT)'] * len(active_ids))
        inactive_query = '''
            UPDATE user_handle
            SET active = 0
            WHERE user_id NOT IN ({});
        '''.format(placeholders)
        active_query = '''
            UPDATE user_handle
            SET active = 1
            WHERE user_id IN ({});
        '''.format(placeholders)
        cur = self.conn.cursor()
        cur.execute(inactive_query, active_ids)
        cur.execute(active_query, active_ids)
        rc = cur.rowcount
        self.conn.commit()
        return rc

    # Rated VC stuff

    def create_rated_vc(self, contest_id: int, start_time: float, finish_time: float, guild_id: str, user_ids: [str]):
        """ Creates a rated vc and returns its id.
        """
        query = ('INSERT INTO rated_vcs '
                 '(contest_id, start_time, finish_time, status, guild_id) '
                 'VALUES ( %s, %s, %s, %s, CAST(%s AS TEXT));')
        id = None
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (contest_id, start_time, finish_time, RatedVC.ONGOING, guild_id))
            id = cur.lastrowid
            for user_id in user_ids:
                query = ('INSERT INTO rated_vc_users '
                         '(vc_id, user_id) '
                         'VALUES (%s , CAST(%s AS TEXT));')
                cur.execute(query, (id, user_id))
        return id

    def get_rated_vc(self, vc_id: int):
        query = ('SELECT * '
                'FROM rated_vcs '
                'WHERE id = %s;')
        vc = self._fetchone(query, params=(vc_id,), cursor_factory=psycopg2.extras.NamedTupleCursor)
        return vc

    def get_ongoing_rated_vc_ids(self):
        query = ('SELECT id '
                 'FROM rated_vcs '
                 'WHERE status = %s;'
                 )
        vcs = self._fetchall(query, params=(RatedVC.ONGOING,))
        vc_ids = [vc[0] for vc in vcs]
        return vc_ids

    def get_rated_vc_user_ids(self, vc_id: int):
        query = ('SELECT user_id '
                 'FROM rated_vc_users '
                 'WHERE vc_id = %s;'
                 )
        users = self._fetchall(query, params=(vc_id,))
        user_ids = [user[0] for user in users]
        return user_ids

    def finish_rated_vc(self, vc_id: int):
        query = ('UPDATE rated_vcs '
                'SET status = %s '
                'WHERE id = %s;')

        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (RatedVC.FINISHED, vc_id))

    def update_vc_rating(self, vc_id: int, user_id: str, rating: int):
        query = ('INSERT INTO rated_vc_users '
                 '(vc_id, user_id, rating) '
                 'VALUES (%s, CAST(%s AS TEXT), %s) '
                 'ON CONFLICT (vc_id, user_id) '
                 'DO UPDATE SET '
                 'rating = EXCLUDED.rating;')

        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (vc_id, user_id, rating))

    def get_vc_rating(self, user_id: str, default_if_not_exist: bool = True):
        result = self.get_vc_rating_history(user_id)
        if not result:
            if default_if_not_exist:
                return _DEFAULT_VC_RATING
            return None
        return result[-1][1]

    def get_vc_rating_history(self, user_id: str):
        """ Return [vc_id, rating].
        """
        query = ('SELECT vc_id, rating '
                 'FROM rated_vc_users '
                 'WHERE user_id = CAST(%s AS TEXT) AND rating IS NOT NULL '
                 'ORDER BY vc_id ASC;'
                 )
        ratings = self._fetchall(query, params=(user_id,))
        return ratings

    def set_rated_vc_channel(self, guild_id, channel_id):
        query = ('INSERT INTO rated_vc_settings '
                 ' (guild_id, channel_id) VALUES (CAST(%s AS TEXT), %s)'
                 'ON CONFLICT (guild_id) '
                 'DO UPDATE SET '
                 'channel_id = EXCLUDED.channel_id;'
                 )
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (guild_id, channel_id))

    def get_rated_vc_channel(self, guild_id):
        query = ('SELECT channel_id '
                 'FROM rated_vc_settings '
                 'WHERE guild_id = CAST(%s AS TEXT);')
        cur = self.conn.cursor()
        cur.execute(query, (guild_id,))
        channel_id = cur.fetchone()
        return int(channel_id[0]) if channel_id else None

    def remove_last_ratedvc_participation(self, user_id: str):
        query = ('SELECT MAX(vc_id) AS vc_id '
                 'FROM rated_vc_users '
                 'WHERE user_id = CAST(%s AS TEXT);'
                 )
        vc_id = self._fetchone(query, params=(user_id, ))
        if vc_id is None:
            return 0
        vc_id = vc_id[0]
        query = ('DELETE FROM rated_vc_users '
                 'WHERE user_id = CAST(%s AS TEXT) AND vc_id = %s;')
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, (user_id, vc_id))
            return cur.rowcount

    def close(self):
        self.conn.close()
