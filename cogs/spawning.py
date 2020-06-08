import random
import time
from functools import cached_property
from pathlib import Path

import discord
from discord.ext import commands

from .database import Database
from .helpers import checks, mongo
from .helpers.models import GameData, LevelTrigger, deaccent


class Spawning(commands.Cog):
    """For basic bot operation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pokemon = {}
        self.users = {}
        self.cooldown = {}
        self.guilds = {}

    @property
    def db(self) -> Database:
        return self.bot.get_cog("Database")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if self.bot.user in message.mentions:
            prefix = await self.bot.get_cog("Bot").determine_prefix(message)
            if type(prefix) == list:
                prefix = prefix[0]
            await message.channel.send(f"My prefix is `{prefix}` in this server.")

        current = time.time()

        # Spamcheck, every two seconds

        if self.bot.env != "dev":
            if current - self.users.get(message.author.id, 0) < 1:
                return

        self.users[message.author.id] = current

        # Increase XP on selected pokemon

        member = await self.db.fetch_member(message.author)

        if member is not None:
            pokemon = member.selected_pokemon

            if pokemon.level < 100 and pokemon.xp <= pokemon.max_xp:
                xp_inc = random.randint(10, 40)

                if member.boost_active:
                    xp_inc += random.randint(10, 40)

                await self.db.update_pokemon(
                    message.author,
                    member.selected,
                    {"$inc": {"pokemon.$.xp": xp_inc},},
                )

            if pokemon.xp > pokemon.max_xp and pokemon.level < 100:
                update = {"$inc": {"pokemon.$.level": 1}, "$set": {"pokemon.$.xp": 0}}
                embed = discord.Embed()
                embed.color = 0xF44336
                embed.title = f"Congratulations {message.author.name}!"
                embed.description = (
                    f"Your {pokemon.species} is now level {pokemon.level + 1}!"
                )

                if pokemon.species.primary_evolution is not None:
                    if (
                        pokemon.level + 1
                        >= pokemon.species.primary_evolution.trigger.level
                    ):
                        embed.add_field(
                            name=f"Your {pokemon.species} is evolving!",
                            value=f"Your {pokemon.species} has turned into a {pokemon.species.primary_evolution.target}!",
                        )
                        update["$set"][
                            "pokemon.$.species_id"
                        ] = pokemon.species.primary_evolution.target_id

                await self.db.update_pokemon(message.author, member.selected, update)

                await message.channel.send(embed=embed)
            elif pokemon.level == 100:
                await self.db.update_pokemon(
                    message.author,
                    member.selected,
                    {"$set": {"pokemon.$.xp": pokemon.max_xp}},
                )

        # Increment guild activity counter

        if self.bot.env != "dev":
            if current - self.cooldown.get(message.guild.id, 0) < 1:
                return

        self.cooldown[message.guild.id] = current
        self.guilds[message.guild.id] = self.guilds.get(message.guild.id, 0) + 1

        if self.guilds[message.guild.id] >= (5 if self.bot.env == "dev" else 15):
            self.guilds[message.guild.id] = 0
            guild = await self.db.fetch_guild(message.guild)

            if guild.channel is not None:
                channel = message.guild.get_channel(guild.channel)
            else:
                channel = message.channel

            await self.spawn_pokemon(channel)

    async def spawn_pokemon(self, channel):
        # Get random species and level, add to tracker

        species = GameData.random_spawn()
        level = min(max(int(random.normalvariate(20, 10)), 1), 100)

        inds = [i for i, x in enumerate(species.name) if x.isalpha()]
        blanks = random.sample(inds, len(inds) // 2)

        hint = "".join([x if i in blanks else "\_" for i, x in enumerate(species.name)])

        self.pokemon[channel.id] = (species, level, hint)

        # Fetch image and send embed

        with open(Path.cwd() / "data" / "images" / f"{species.id}.png", "rb") as f:
            image = discord.File(f, filename="pokemon.png")

        embed = discord.Embed()
        embed.color = 0xF44336
        embed.title = f"A wild pokémon has appeared!"
        embed.description = (
            "Guess the pokémon and type `p!catch <pokémon>` to catch it!"
        )
        embed.set_image(url="attachment://pokemon.png")

        await channel.send(file=image, embed=embed)

    @checks.has_started()
    @commands.command()
    async def hint(self, ctx: commands.Context):
        """Get a hint for the wild pokémon."""

        if ctx.channel.id not in self.pokemon:
            return

        species, level, hint = self.pokemon[ctx.channel.id]
        await ctx.send(f"The pokémon is {hint}.")

    @checks.has_started()
    @commands.command()
    async def catch(self, ctx: commands.Context, *, guess: str):
        """Catch a wild pokémon."""

        # Retrieve correct species and level from tracker

        if ctx.channel.id not in self.pokemon:
            return

        species, level, hint = self.pokemon[ctx.channel.id]

        if deaccent(guess.lower()) not in species.correct_guesses:
            return await ctx.send("That is the wrong pokémon!")

        # Correct guess, add to database

        del self.pokemon[ctx.channel.id]

        member = await self.db.fetch_member(ctx.author)

        await self.db.update_member(
            ctx.author,
            {
                "$inc": {"next_id": 1,},
                "$push": {
                    "pokemon": {
                        "number": member.next_id,
                        "species_id": species.id,
                        "level": level,
                        "xp": 0,
                        "owner_id": ctx.author.id,
                        "nature": mongo.random_nature(),
                        "iv_hp": mongo.random_iv(),
                        "iv_atk": mongo.random_iv(),
                        "iv_defn": mongo.random_iv(),
                        "iv_satk": mongo.random_iv(),
                        "iv_sdef": mongo.random_iv(),
                        "iv_spd": mongo.random_iv(),
                    }
                },
            },
        )

        message = f"Congratulations {ctx.author.mention}! You caught a level {level} {species}!"

        if str(species.id) not in member.pokedex:
            message += " Added to Pokédex. You received 35 credits!"

            await self.db.update_member(
                ctx.author,
                {"$set": {f"pokedex.{species.id}": 1}, "$inc": {"balance": 35},},
            )

        else:
            inc_bal = 0

            if member.pokedex[str(species.id)] == 10:
                message += f" This is your 10th {species}! You received 350 credits."
                inc_bal = 350

            elif member.pokedex[str(species.id)] == 100:
                message += f" This is your 100th {species}! You received 3500 credits."
                inc_bal = 3500

            elif member.pokedex[str(species.id)] == 1000:
                message += (
                    f" This is your 1000th {species}! You received 35000 credits."
                )
                inc_bal = 35000

            await self.db.update_member(
                ctx.author,
                {"$set": {f"pokedex.{species.id}": 1}, "$inc": {"balance": inc_bal},},
            )

        await ctx.send(message)

    @checks.is_admin()
    @commands.command()
    async def redirect(self, ctx: commands.Context, *, channel: discord.TextChannel):
        """Redirect pokémon catches to one channel."""

        await self.db.update_guild(ctx.guild, {"$set": {"channel": channel.id}})

        await ctx.send(f"Now redirecting all pokémon spawns to {channel.mention}")
