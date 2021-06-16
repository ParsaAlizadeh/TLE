import json
import random
import re

import discord
from discord.ext import commands

from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import discord_common
from tle.util import paginator


class HOICogError(commands.CommandError):
    pass


def _load_list(name, cutoff):
    class Wrapper(dict):
        def cnt(self, prob: cf.Problem):
            return self[prob.contest_identifier]

        def has(self, prob: cf.Problem):
            return prob.contest_identifier in self

    with open(f'data/list/{name}.json', 'r') as file:
        priority = json.load(file)
        priority = {prob: cnt for prob, cnt in priority.items() if cnt >= cutoff}
        return Wrapper(priority)


class HOI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.converter = commands.MemberConverter()

    @commands.group(brief='HOI commands',
                    invoke_without_command=True)
    async def hoi(self, ctx):
        """Customized commands for hoi version"""
        await ctx.send_help('hoi')

    @hoi.command(brief='Check status for a problem',
                 usage='problemid')
    async def check(self, ctx, idx: str):
        match = re.match(r"^(\d+)([a-zA-Z]\d?)$", idx)
        if not match:
            raise HOICogError('Problem not found')
        contest, problem = match.groups()
        pb_link = f"https://codeforces.com/problemset/status/{contest}/problem/{problem}?list" \
                  f"=f53e67ca4a5f784f27d39a4aea8dfd19 "
        await ctx.send(pb_link)

    @hoi.command(brief='Get the link of problem (cf / atcoder)',
                 usage='problemid')
    async def link(self, ctx, idx: str):
        """Get problem link by id (cf / atcoder)"""
        cf_match = re.match(r"^(\d+)([a-zA-Z]\d?)$", idx)
        at_match = re.match(r"^(a[brg]c\d{,3})([a-zA-Z])$", idx)

        pb_link = None
        if cf_match:
            contest, problem = cf_match.groups()
            pb_link = "https://codeforces.com/{0}/{1}/problem/{2}".format(
                "contest" if len(contest) < 6 else "gym",
                contest,
                problem.upper()
            )
        elif at_match:
            contest, problem = at_match.groups()
            contest = contest[:3] + ("0" * (6 - len(contest))) + contest[3:]
            pb_link = f"https://atcoder.jp/contests/{contest}/tasks/{contest}_{problem.upper()}"

        if not pb_link:
            raise HOICogError('Problem not found')

        await ctx.send(pb_link)

    @hoi.command(brief='Recommend a (good) problem',
                 usage='name [tags...] [rating] [>=cutoff]')
    @cf_common.user_guard(group='gitgud')
    async def givlist(self, ctx, name, *args):
        """Recommand random problem, based on solved by people in list"""
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        rating = round(cf_common.user_db.fetch_cf_user(handle).effective_rating, -2)
        tags = []
        cutoff = 0
        for arg in args:
            if arg.isdigit():
                rating = int(arg)
            elif arg[:2] == ">=":
                cutoff = int(arg[2:])
            else:
                tags.append(arg)

        priority = _load_list(name, cutoff)

        submissions = await cf.user.status(handle=handle)
        solved = {sub.problem.name for sub in submissions if sub.verdict == 'OK'}

        problems = [prob for prob in cf_common.cache2.problem_cache.problems
                    if prob.rating == rating and prob.name not in solved and priority.has(prob)]
        if tags:
            problems = [prob for prob in problems if prob.tag_matches(tags)]

        if not problems:
            raise HOICogError('Problems not found within the search parameters')

        problems.sort(key=priority.cnt)
        choice = max([random.randrange(len(problems)) for _ in range(4)])
        problem = problems[choice]
        cnt = priority.cnt(problem)
        await ctx.send(f"{cnt} people solved this !!!")
        await ctx.send(f"valid problems: {len(problems)}, "
                       f"min solved: {priority.cnt(problems[0])}, "
                       f"max solved: {priority.cnt(problems[-1])}")

        title = f'{problem.index}. {problem.name}'
        desc = cf_common.cache2.contest_cache.get_contest(problem.contestId).name
        embed = discord.Embed(title=title, url=problem.url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        if tags:
            tagslist = ', '.join(problem.tag_matches(tags))
            embed.add_field(name='Matched tags', value=tagslist)
        await ctx.send(f'Recommended problem for `{handle}`', embed=embed)

    @hoi.command(brief='Create a (good) mashup', usage='name [lower:upper] [handles] [+tags]')
    async def bestlist(self, ctx, name: str, *args):
        """Create a mashup contest using problems with maximum solved by list members."""

        def make_page(chunk, title):
            nonlocal priority
            desc = '\n'.join(f'[{p.name}]({p.url}) [{p.rating}] {priority.cnt(p)}x'
                             for i, p in enumerate(chunk))
            embed = discord_common.cf_color_embed(description=desc)
            return title, embed

        handles = [arg for arg in args if arg[0] != '+' and arg[0] != '~' and ":" not in arg]
        tags = [arg[1:] for arg in args if arg[0] == '+' and len(arg) > 1]
        not_tags = [arg[1:] for arg in args if arg[0] == '~' and len(arg) > 1]

        rate_range = [arg for arg in args if ":" in arg]
        if len(rate_range) > 1:
            raise HOICogError('More than one lower:upper')
        if not rate_range:
            rate_range = [':']

        lower, upper = rate_range[0].split(":")
        lower = int(lower) if lower else 0
        upper = int(upper) if upper else 9999

        priority = _load_list(name, 0)
        handles = handles or ('!' + str(ctx.author),)
        handles = await cf_common.resolve_handles(ctx, self.converter, handles)

        resp = [await cf.user.status(handle=handle) for handle in handles]
        submissions = [sub for user in resp for sub in user]
        solved = {sub.problem.name for sub in submissions}
        problems = [prob for prob in cf_common.cache2.problem_cache.problems
                    if lower <= prob.rating <= upper and prob.name not in solved
                    and not any(cf_common.is_contest_writer(prob.contestId, handle) for handle in handles)
                    and not cf_common.is_nonstandard_problem(prob)
                    and priority.has(prob)]
        if tags:
            problems = [prob for prob in problems if prob.tag_matches(tags)]
        if not_tags:
            problems = [prob for prob in problems if not any(prob.tag_matches([tag]) for tag in not_tags)]

        problems.sort(key=priority.cnt)
        problems.reverse()

        title = f"Found {len(problems)} valid problem for `{'`, `'.join(handles)}`"
        pages = [make_page(chunk, title) for chunk in paginator.chunkify(problems, 20)]
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=5 * 60, set_pagenum_footers=True)

    @discord_common.send_error_if(HOICogError, cf_common.ResolveHandleError, cf_common.FilterError)
    async def cog_command_error(self, ctx, error):
        pass


def setup(bot):
    bot.add_cog(HOI(bot))
