from discord import Interaction, Embed
from src.utils.db import get_db_connection
from src.utils.wallet import modify_user_balance
from src.utils.format import format_amount
from src.utils.embed import set_bot_footer
import random
import time
import discord

JOKES = [
    "Pourquoi les plongeurs plongent-ils toujours en arrière ? Parce que sinon ils tomberaient dans le bateau !",
    "Quel est le comble d'un électricien ? De ne pas être au courant !",
    "Quel est le pain préféré des programmeurs ? Le pain bis (byte) !",
    "Pourquoi les poissons ne jouent-ils pas au poker ? Parce qu'il y a trop de requins !",
    "Quel est le comble d'un jardinier ? De ne pas savoir planter un clou !",
    "Pourquoi les informaticiens confondent-ils Halloween et Noël ? Parce que OCT 31 = DEC 25 !",
    "Quel est le comble d'un chauffeur ? De prendre le train pour aller au travail !",
    "Pourquoi les oiseaux volent-ils en formation en V ? Pour payer moins de péage !",
    "Quel est le comble d'un couvreur ? De ne pas trouver le toit de sa maison !",
    "Quel est le comble d'un boucher ? De ne pas avoir le cœur à l'ouvrage !",
    "Quel est le comble d'un astronome ? De ne pas voir plus loin que son nez !",
    "Pourquoi les boulangers sont-ils toujours de bonne humeur ? Parce que leur métier c'est du gâteau !",
    "Quel est le comble d'un horloger ? De ne jamais avoir une minute à lui !",
    "Quel est le comble d'un bibliothécaire ? De ne pas savoir où ranger ses livres !",
    "Pourquoi les vétérinaires sont-ils toujours débordés ? Parce que leurs patients ne prennent jamais de rendez-vous !",
    "Quel est le comble d'un facteur ? De ne jamais avoir le temps de lire son courrier !",
    "Quel est le comble d'un pompier ? De ne pas trouver la sortie !",
    "Quel est le comble d'un dentiste ? D'avoir les dents du bonheur !",
    "Pourquoi les avocats travaillent-ils si tard ? Parce que la justice est lente mais eux ne le sont pas !",
    "Quel est le comble d'un joueur d'échecs ? De ne pas savoir quoi faire de sa reine !",
    "Quel est le comble d'un médecin ? D'être malade comme un chien !",
    "Quel est le comble d'un mécanicien ? De tomber en panne sur l'autoroute !",
    "Pourquoi les photographes sont-ils toujours zen ? Parce qu'ils savent prendre du recul !",
    "Pourquoi les enseignants portent-ils des lunettes ? Pour mieux voir leurs élèves... de loin !",
    "Quel est le comble d'un coiffeur ? D'être à bout de nerfs !",
    "Pourquoi les informaticiens n'aiment-ils pas la nature ? Parce qu'il y a trop de bugs !",
    "Quel est le comble d'un géographe ? De ne pas savoir où il habite !",
    "Pourquoi les cyclistes pédalent-ils si vite ? Pour ne pas se faire doubler par leurs idées !",
    "Quel est le comble d'un cuisinier ? De manquer de recul !",
    "Pourquoi les fantômes sont-ils de mauvais menteurs ? Parce qu'on voit à travers eux !",
    "Quel est le comble d'un pêcheur ? De ne pas savoir nager !",
    "Pourquoi les squelettes ne se battent-ils jamais ? Parce qu'ils n'ont pas le cœur à ça !",
    "Quel est le comble d'un alpiniste ? D'avoir le vertige de ses succès !",
    "Pourquoi les vaches portent-elles des cloches ? Parce que leurs cornes ne fonctionnent pas !",
    "Quel est le comble d'un boulanger ? D'être dans le pétrin !",
    "Pourquoi les plantes ne parlent-elles pas ? Parce qu'elles ont la langue dans leur pot !",
    "Quel est le comble d'un nageur ? De couler à pic dans ses examens !",
    "Pourquoi les banquiers sont-ils si calmes ? Parce qu'ils ont des intérêts à ménager !",
    "Quel est le comble d'un musicien ? De perdre la note !",
    "Pourquoi les chats sont-ils sur Internet ? Parce qu'ils cherchent des souris !",
    "Quel est le comble d'un peintre ? De ne pas voir les choses en couleur !",
    "Pourquoi les montres suisses sont-elles si précises ? Parce qu'elles ont du temps devant elles !",
    "Quel est le comble d'un astronaute ? D'avoir les pieds sur terre !",
    "Pourquoi les livres de maths sont-ils tristes ? Parce qu'ils ont trop de problèmes !",
    "Quel est le comble d'un menuisier ? De ne pas savoir sur quel pied danser !",
    "Pourquoi les éléphants ne jouent-ils pas aux cartes dans la jungle ? Parce qu'il y a trop de tricheurs !",
    "Quel est le comble d'un joueur de tennis ? De faire une faute de frappe !",
    "Pourquoi les robots ne mangent-ils pas ? Parce qu'ils ont déjà des puces !",
    "Quel est le comble d'un archéologue ? D'avoir une carrière en ruines !",
    "Pourquoi les abeilles bourdonnent-elles ? Parce qu'elles ne savent pas les paroles !",
]

async def register(bot):
    @bot.tree.command(
        name="work",
        description="Travailler pour gagner de l'argent (utilisable 1x par semaine)."
    )
    async def work(interaction: Interaction):
        db = get_db_connection()
        cursor = db.cursor()
        user_id = interaction.user.id
        current_time = int(time.time())

        cursor.execute("SELECT last_work FROM users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()

        if result:
            last_work = result[0]
            if last_work is not None:
               
                if current_time - last_work < 604800:
               
                    remaining = 604800 - (current_time - last_work)
                    days = remaining // 86400
                    hours = (remaining % 86400) // 3600
                    minutes = (remaining % 3600) // 60

                    embed = Embed(
                        title="⏰ Cooldown actif",
                        description=f"Tu pourras travailler à nouveau dans **{days}j {hours}h {minutes}min**.",
                        color=discord.Color.orange()
                    )
                    set_bot_footer(embed, interaction)
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    db.close()
                    return
        else:
         
            cursor.execute("INSERT INTO users (user_id, last_work) VALUES (%s, %s)", (user_id, 0))
            db.commit()

        gain = random.randint(50, 250)

        new_balance = await modify_user_balance(db, interaction.guild_id, user_id, gain, "add")

        cursor.execute("UPDATE users SET last_work = %s WHERE user_id = %s", (current_time, user_id))
        db.commit()

        joke = random.choice(JOKES)

        embed = Embed(
            title="💼 Travail terminé !",
            description=f"Tu as gagné **{format_amount(gain)}💰** !\n\n**😄 Blague du jour :**\n_{joke}_\n\n📊 Nouveau solde : **{format_amount(new_balance)}💰**",
            color=discord.Color.green()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=False)
        db.close()