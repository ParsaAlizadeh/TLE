**8 Oct 2023:**
I archived this repository, because [Heroku decided to stop supporting free tier and free plan for Postgres](https://blog.heroku.com/next-chapter).
The setup here might still be usable, but I won't maintain it anymore.

**6 Apr 2021:**
The master branch is almost deprecated. Heroku files can be used again, but if you are looking for ready-to-use version, you can see [fishy15/TLE
](https://github.com/fishy15/TLE/tree/heroku) or [hoi branch](https://github.com/ParsaAlizadeh/TLE/tree/hoi) (customized TLE).

# TLE (+ Heroku)

This repository helps to run TLE directly in the heroku. For more information about TLE, check the [main repository](https://github.com/cheran-senthil/TLE).


## Steps for hosting a bot for your own server using Heroku.

1. Download the heroku CLI from [here](https://devcenter.heroku.com/articles/heroku-cli)
2. Now after installing the CLI, open up the CLI if you are on windows or open up a terminal if you are on linux.
3. Now enter the command `heroku login` and it will open up a link in the browser for login. Login using your credentials.
4. Now clone this repository from the terminal using the command `git clone https://github.com/ParsaAlizadeh/TLE.git`.
5. After cloning move into the TLE directory using `cd TLE`.
6. Now enter `heroku create` command in the terminal and hit enter. It will create a new app for you. Remember the name.
7. Now you need to add two buildpacks to deploy. The APT buildpack to install essential APT files and Python buildpack to install essential packages.
8. To add APT buildpack type the following command `heroku buildpacks:add heroku-community/apt`.
9. To add Python buildpack type the following command `heroku buildpacks:add heroku/python`.
    > **Note**: the order of adding the buildpacks is important.
10. Now go to the personal dashboard [page](https://dashboard.heroku.com/apps) of heroku on your browser.
11. Next click on the app you created in step 6.
12. Go to settings tab and you will see a section called **Config Vars**. Click on the **reveal config vars** button.
13. Now you need to create a config var called `BOT_TOKEN` and paste your bot token created using discord and hit add.
14. Now you are almost done. Type the following command `git push heroku master` and press enter.
15. It will take few minutes to build and deploy
16. After successful build open the heroku app in your browser. The same step as 10.
17. Go to Resources tab and turn on the worker. You are not charged for doing this its completely free.
18. That's it Enjoy!
