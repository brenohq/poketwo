import random
from pathlib import Path

import discord
from discord.ext import commands

from .database import Database
from .helpers import checks
from .helpers.models import GameData


class Spawning(commands.Cog):
    """For basic bot operation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pokemon = {}

    @property
    def db(self) -> Database:
        return self.bot.get_cog("Database")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        guild = self.db.fetch_guild(message.guild)
        guild.update(inc__counter=1)

        if guild.counter >= 50:
            guild.update(counter=0)
            
            if guild.channel is not None:
                channel = message.guild.get_channel(guild.channel)
            else:
                channel = message.channel

            await self.spawn_pokemon(channel)

    async def spawn_pokemon(self, channel):
        species = GameData.species_by_number(random.randint(1, 807))
        level = min(max(int(random.normalvariate(20, 10)), 1), 100)

        self.pokemon[channel.id] = (species, level)

        with open(Path.cwd() / "data" / "images" / f"{species.id}.png", "rb") as f:
            image = discord.File(f, filename="pokemon.png")

        embed = discord.Embed()
        embed.color = 0xF44336
        embed.title = f"A wild pokémon has appeared!"
        embed.description = (
            "Guess the pokémon and type `p!catch <pokémon>` to catch it!"
        )
        embed.set_image(url="attachment://pokemon.png")
        embed.set_footer(text="This bot is in test mode. All data will be reset.")

        await channel.send(file=image, embed=embed)

    @checks.has_started()
    @commands.command()
    async def catch(self, ctx: commands.Context, guess: str):
        if ctx.channel.id not in self.pokemon:
            return

        species, level = self.pokemon[ctx.channel.id]

        if guess.lower() != species.name.lower():
            return await ctx.send("That is the wrong pokémon!")

        del self.pokemon[ctx.channel.id]

        member_data = self.db.fetch_member(ctx.author)
        next_id = member_data.next_id
        member_data.update(inc__next_id=1)

        member_data.pokemon.create(
            number=member_data.next_id,
            species_id=species.id,
            level=level,
            owner_id=ctx.author.id,
        )
        member_data.save()

        await ctx.send(
            f"Congratulations {ctx.author.mention}! You caught a level {level} {species}!"
        )

    @checks.is_admin()
    @commands.command()
    async def redirect(self, ctx: commands.Context, channel: discord.TextChannel):
        guild = self.db.fetch_guild(ctx.guild)
        guild.update(channel=channel.id)

        await ctx.send(f"Now redirecting all pokémon spawns to {channel.mention}")