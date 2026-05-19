import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import json
import os
from datetime import datetime, timezone
from threading import Thread
from io import BytesIO
from PIL import Image
import asyncio
import traceback
import time 
from discord.ext import tasks
import shutil

db_lock = asyncio.Lock()
event_lock = asyncio.Lock()

db_lock = None
event_lock = None

TOKEN = os.getenv("TOKEN")

DB_FILE = "/data/database.db" 
DATA_FILE = "data.json" 
BACKUP_FILE = "data_backup.json"

BATTLE_REPORT_CHANNEL_ID = 1500525099655102525
TECHSORCIST_RECORDS_CHANNEL_ID = 1505702243666497688
EVENTS_CHANNEL_ID = 1506016793691426936

event_active = False

intents = discord.Intents.default() 
intents.members = True 
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@tasks.loop(hours=1)
async def monthly_double_rites_event():
    global event_active

    now = datetime.now(timezone.utc)
    day = now.day

    channel = bot.get_channel(1500521032753217657)

    async with event_lock:
        if 20 <= day <= 23:
            if not event_active:
                event_active = True
                print("🔥 Double Rites Event STARTED 🔥")
        else:
            if event_active:
                event_active = False
                print("❌ Double Rites Event ENDED ❌")
  
def init_db(): 
    
    conn = sqlite3.connect(DB_FILE) 
    cursor = conn.cursor()

    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS members (
            user_id TEXT PRIMARY KEY,
            rites INTEGER DEFAULT 0,
            gene INTEGER DEFAULT 0,
            relics TEXT DEFAULT '[]',
            completed_challenges TEXT DEFAULT '[]'
        )
    """)

    conn.commit()
    conn.close()

init_db()

def migrate_json():
    if not os.path.exists("data.json"):
        return

    with open("data.json", "r") as f:
        data = json.load(f)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    for uid, user in data.get("members", {}).items():
        cursor.execute("""
            INSERT OR IGNORE INTO members (user_id, rites, gene, relics, completed_challenges)
            VALUES (?, ?, ?, ?, ?)
        """, (
            uid,
            user.get("rites", 0),
            user.get("gene", 0),
            json.dumps(user.get("relics", [])),
            json.dumps(user.get("completed_challenges", []))
        ))

    conn.commit()
    conn.close()

    print("✅ Migration complete")

migrate_json()

def get_member_days(member: discord.Member):
    if not member.joined_at:
        return 0
    return (datetime.now(timezone.utc) - member.joined_at).days

def battle_reports_only():
    async def predicate(interaction: discord.Interaction):
        if interaction.channel_id != BATTLE_REPORT_CHANNEL_ID:
            await interaction.response.send_message(
                "❌ Battle reports may only be used in the designated Battle Reports channel.",
                ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)

def events_channel_only():
    async def predicate(interaction: discord.Interaction):
        if interaction.channel_id != EVENTS_CHANNEL_ID:
            await interaction.response.send_message(
                "Event requests may only be used in the Events channel.",
                ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)

def techsorcist_records_only():
    async def predicate(interaction: discord.Interaction):
        if interaction.channel_id != TECHSORCIST_RECORDS_CHANNEL_ID:
            await interaction.response.send_message(
                "📜 This command may only be used in Techsorcist Records.",
                ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)

# =========================
# HELPERS (PUT GRID HERE)
# =========================
async def make_grid_image(attachments, cols=2):
    try:
        MAX_IMAGE_SIZE = 900 # max width/height per image
        MAX_TOTAL_PIXELS = 8_000_000 # hard safety cap

        images = []

        for att in attachments:
            data = await asyncio.wait_for(att.read(), timeout=5)

            bio = BytesIO(data)

            with Image.open(bio) as img:
                
            
            
                img = img.convert("RGB")

                # 🔥 Resize safely
                img.thumbnail((MAX_IMAGE_SIZE, MAX_IMAGE_SIZE))

                images.append(img.copy())
            bio.close()    
            
        if not images:
            return None

        w, h = images[0].size
        rows = (len(images) + cols - 1) // cols
        
        total_width = cols * w
        total_height = rows * h

        # 🔥 Hard crash prevention
        if total_width * total_height > MAX_TOTAL_PIXELS:
            print("Grid too large — resizing further")

            scale = (MAX_TOTAL_PIXELS / (total_width * total_height)) ** 0.5

            new_w = int(w * scale)
            new_h = int(h * scale)

            resized = []
            for img in images:
                img = img.resize((new_w, new_h))
                resized.append(img)

            images = resized
            w, h = new_w, new_h
            total_width = cols * w
            total_height = rows * h

        grid = Image.new("RGB", (total_width, total_height), (20, 20, 20))

        for i, img in enumerate(images):
            x = (i % cols) * w
            y = (i // cols) * h
            grid.paste(img, (x, y))

        buffer = BytesIO()
        grid.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)

        grid.close()
        for img in images:
            img.close()

        return buffer

    except Exception as e:
        print(f"Image processing error: {e}")
        return None
    
class EventApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "❌ Administrator permission required.",
                ephemeral=True
            )

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.set_footer(text=f"Approved by {interaction.user}")

        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message("✅ Event approved.", ephemeral=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "❌ Administrator permission required.",
                ephemeral=True
            )

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.set_footer(text=f"Denied by {interaction.user}")

        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message("❌ Event denied.", ephemeral=True)

# ==================================================
# RANK SYSTEM
# ==================================================

RANKS = {
    24: "Scout",
    75: "Battle Brother",
    125: "Brother-Initiate",
    250: "Veteran",
    350: "Bladeguard Veteran",
    500: "Sergeant",
    650: "Lector",
    725: "Lector-Sergeant",
    850: "Ancient",
    1200: "Lieutenant",
    1500: "Almoner",
    2000: "Almoner-Lieutenant"
}

# ==================================================
# RELIC REWARDS SYSTEM
# ==================================================

RELICS = {
    "Hellslayer": {"gene": 45, "rites": 125},
    "Serpent Staff of Sabazius": {"gene": 65, "rites": 125},
    "Cessation": {"gene": 75, "rites": 250},
    "Liber Exorcismus": {"gene": 85, "rites": 250},
    "Expulsiaris": {"gene": 90, "rites": 350},
    "Silent Cry": {"gene": 100, "rites": 500},
    "Exile Plate": {"gene": 120, "rites": 650},
    "Voidbane": {"gene": 135, "rites": 650},
    "Daemonarchia Claviculus": {"gene": 200, "rites": 1200},
}

CHALLENGE_TO_RANK = {
    "Welcome to the Exorcists": "Scout",
    "Battle Brother": "Battle Brother",
    "Initiate Trials": "Brother-Initiate",
    "Scholar": "Lexicanum",
    "Emperor's Might": "Judiciar",
    "Mechanicus": "Tech Adept",
    "Thrice Sealed Chalice": "Helix Adept",
    "Emperor's Blade": "Bladeguard Veteran",
    "Enochian": "Enochian Guard",
    "Apothecary": "Apothecary",
    "Techmarine": "Techmarine",
    "Banisher": "Librarian",
    "Experienced Orison Member": "Lector",
    "Warden of Purgatomb": "Daemonium Palatinae",
    "Orison Leader": "Lector-Sergeant",
    "Standard Bearer": "Ancient"

}
# ==================================================
# DIFFICULTY VALUES
# ==================================================

OPERATION_DIFFICULTY = {
    "Ruthless": 2,
    "Lethal": 3,
    "Absolute": 4
}

STRATAGEM_DIFFICULTY = {
    "Normal": 3,
    "Hard": 5
}

# ==================================================
# DROPDOWN CHOICES
# ==================================================

VICTORY_CHOICES = [
    app_commands.Choice(name="Yes", value="Yes"),
    app_commands.Choice(name="No", value="No"),
]

OPERATION_DIFFICULTY_CHOICES = [
    app_commands.Choice(name="Ruthless", value="Ruthless"),
    app_commands.Choice(name="Lethal", value="Lethal"),
    app_commands.Choice(name="Absolute", value="Absolute"),
]

STRATAGEM_DIFFICULTY_CHOICES = [
    app_commands.Choice(name="Normal", value="Normal"),
    app_commands.Choice(name="Hard", value="Hard"),
]

WAVE_CHOICES = [
    app_commands.Choice(name="5", value=5),
    app_commands.Choice(name="10", value=10),
    app_commands.Choice(name="15", value=15),
    app_commands.Choice(name="20", value=20),
]

GENE_CHOICES = [
    app_commands.Choice(name="Found", value="Found"),
    app_commands.Choice(name="Not Found", value="Not Found"),
]

MISSION_LIST = [
    "Inferno", "Decapitation", "Vox Liberatis", "Reliquary",
    "Fall of Atreus", "Ballistic Engine", "Termination",
    "Obelisk", "Exfiltration", "Vortex",
    "Reclamation", "Disruption"
]

MISSION_CHOICES = [app_commands.Choice(name=m, value=m) for m in MISSION_LIST]

# ==================================================
# DATA SYSTEM
# ==================================================

def get_user(uid: int | str):
    uid = str(uid)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT rites, gene, relics, completed_challenges
        FROM members
        WHERE user_id = ?
    """, (str(uid),))

    row = cursor.fetchone()
    conn.close()

    # If user doesn't exist yet
    if not row:
        return {
            "rites": 0,
            "gene": 0,
            "relics": [],
            "completed_challenges": []
        }

    return {
        "rites": row[0],
        "gene": row[1],
        "relics": json.loads(row[2]),
        "completed_challenges": json.loads(row[3])
    }

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"members": {}}

    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)

    except json.JSONDecodeError:
        print("⚠️ Data file corrupted. Attempting backup restore.")

        if os.path.exists(BACKUP_FILE):
            with open(BACKUP_FILE, "r") as f:
                return json.load(f)

        return {"members": {}}


def save_data(data):
    temp_file = "data_temp.json"

    # Create backup first
    if os.path.exists(DATA_FILE):
        shutil.copy(DATA_FILE, BACKUP_FILE)

    # Write to temp file
    with open(temp_file, "w") as f:
        json.dump(data, f, indent=4)

    # Atomic replace (crash-safe)
    os.replace(temp_file, DATA_FILE)

def ensure_user(user: dict):
    """Guarantees all required fields exist for a user."""
    user.setdefault("rites", 0)
    user.setdefault("gene", 0)
    user.setdefault("relics", [])
    user.setdefault("completed_challenges", [])
    return user

async def add_rites(member, amount, gene_bonus=0):
    global event_active

    if event_active:
        amount *= 2

    uid = str(member.id)

    async with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO members (user_id)
            VALUES (?)
        """, (uid,))

        cursor.execute("""
            UPDATE members
            SET rites = rites + ?, gene = gene + ?
            WHERE user_id = ?
        """, (amount, gene_bonus, uid))

        conn.commit()

        cursor.execute("""
            SELECT rites, gene, relics, completed_challenges
            FROM members
            WHERE user_id = ?
        """, (uid,))

        row = cursor.fetchone()
        conn.close()

    return {
        "rites": row[0],
        "gene": row[1],
        "relics": json.loads(row[2]),
        "completed_challenges": json.loads(row[3])
    }


# ==================================================
# CHALLENGE SYSTEM
# ==================================================
CHALLENGE_REQUIREMENTS = {
    "Scout": {
        "rites": 24
    },

    "Battle Brother": {
        "rites": 75,
        "days": 7
    },

    "Brother-Initiate": {
        "rites": 125,
        "approval": True
    },
    "Lexicanum": {
        "rites": 125,
        "approval": True
},
    "Judiciar": {
        "rites": 125,
        "approval": True
    },

    "Tech Adept": {
        "rites": 125,
        "approval": True
    },

    "Helix Adept": {
        "rites": 125,
        "approval": True
    },


    "Bladeguard Veteran": {
        "rites": 350,
        "approval": True
    },

    "Enochian Guard": {
        "rites": 0,
        "approval": True,
        "special": "Must be Veteran"
    },

    "Sergeant": {
        "rites": 500
    },

    "Techmarine": {
        "rites": 500,
        "approval": True
    },

    "Librarian": {
        "rites": 500,
        "approval": True
    },

    "Apothecary": {
        "rites": 500,
        "approval": True
    },

    "Lector": {
        "rites": 650,
        "approval": True
    },

    "Daemonium Palatinae": {
        "approval": True,
        "days": 60,
        "special": "Must be Enochian Guard"
    },

    "Lector-Sergeant": {
        "rites": 725,
        "approval": True
    },

    "Ancient": {
        "rites": 850,
        "approval": True
    }
}

CHALLENGES = {
    "Scout": {"emoji": "🔥", "auto": True},
    "Battle Brother": {"emoji": "🪖", "auto": True},
    "Brother-Initiate": {"emoji": "🕯️", "auto": False},
    "Lexicanum": {"emoji": "📚", "auto": False},
    "Judiciar": {"emoji": "💀", "auto": False},
    "Tech Adept": {"emoji": "🤖", "auto": False},
    "Helix Adept": {"emoji": "⛑️", "auto": False},
    "Bladeguard Veteran": {"emoji": "⚔️", "auto": False},
    "Enochian Guard": {"emoji": "⛓️", "auto": False},
    "Techmarine": {"emoji": "⚙️", "auto": False},
    "Librarian": {"emoji": "📖", "auto": False},
    "Apothecary": {"emoji": "⚕️", "auto": False},
    "Lector": {"emoji": "🧿", "auto": False},
    "Daemonium Palatinae": {"emoji": "🪦", "auto": False},
    "Lector-Sergeant": {"emoji": "☠️", "auto": False},
    "Ancient": {"emoji": "📜", "auto": False},
}
CHALLENGE_CHOICES = [
    app_commands.Choice(name=name, value=name)
    for name in CHALLENGES.keys()
]
# ==================================================
# RANK LOGIC
# ==================================================

def get_rank_with_time(member: discord.Member, total):

    days = get_member_days(member)

    rank = "Aspirant"

    for threshold in sorted(RANKS.keys()):
        if total >= threshold:
            potential = RANKS[threshold]

            # Veteran requires 30 days
            if potential == "Veteran" and days < 30:
                continue

            rank = potential

    return rank

def get_next_rank(total):
    for threshold in sorted(RANKS.keys()):
        if total < threshold:
            return RANKS[threshold], threshold
    return None, None

def progress_bar(current, target, length=18):
    if not target:
        return "████████████████ MAX"
    filled = int((current / target) * length)
    return "█" * filled + "░" * (length - filled) + f" {current}/{target}"

def get_progress_text(total):
    next_rank, next_req = get_next_rank(total)
    if not next_rank:
        return "MAX RANK"
    return f"Next: {next_rank}\n{progress_bar(total, next_req)}"

async def update_rank_cached(member: discord.Member, user: dict):
    uid = str(member.id)

    new_rank = get_rank_with_time(member, user["rites"])

    roles = {role.name: role for role in member.guild.roles}

    rank_roles = [roles.get(r) for r in RANKS.values()]
    rank_roles = [r for r in rank_roles if r]

    remove = [r for r in rank_roles if r in member.roles and r.name != new_rank]

    if remove:
        await member.remove_roles(*remove)

    new_role = roles.get(new_rank)
    if new_role:
        await member.add_roles(new_role)

    if new_rank in CHALLENGES:
        challenge = CHALLENGES[new_rank]
        if challenge["auto"] and new_rank not in user["completed_challenges"]:
            user["completed_challenges"].append(new_rank)

    # SINGLE DB WRITE ONLY
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE members
        SET completed_challenges = ?
        WHERE user_id = ?
    """, (json.dumps(user["completed_challenges"]), uid))

    conn.commit()
    conn.close()
    
async def check_relics_cached(member: discord.Member, user: dict):
    uid = str(member.id)

    unlocked = []

    for relic, req in RELICS.items():
        if relic in user["relics"]:
            continue

        if user["gene"] >= req["gene"] and user["rites"] >= req["rites"]:
            user["relics"].append(relic)
            unlocked.append(relic)

    if unlocked:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE members
            SET relics = ?
            WHERE user_id = ?
        """, (json.dumps(user["relics"]), uid))

        conn.commit()
        conn.close()

    return unlocked

# ==================================================
# HELPERS
# ==================================================
async def safe_defer(interaction):
    if not interaction.response.is_done():
        await interaction.response.defer()
        
def build_members(*members):
    return [m for m in members if m]


async def send_gallery(interaction, embed, screenshots, content=None):
    if not screenshots:
        await interaction.followup.send(content=content, embed=embed)
        return

    grid_image = await make_grid_image(screenshots, 2)

    if not grid_image:
        await interaction.followup.send(content=content, embed=embed)
        return

    file = discord.File(grid_image, filename="grid.png")
    embed.set_image(url="attachment://grid.png")

    await interaction.followup.send(
        content=content,
        embed=embed,
        file=file
    )

    grid_image.close()

# ==================================================
# ADMIN COMMAND
# ==================================================

@bot.tree.command(name="add_rites")
async def add_rites_cmd(interaction: discord.Interaction, member: discord.Member, amount: int, reason: str = "None"):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)

    await safe_defer(interaction)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE members
        SET rites = rites + ?
        WHERE user_id=?
    """, (amount, str(member.id)))

    conn.commit()
    conn.close()

    user = get_user(member.id)

    await update_rank_cached(member, user)

    embed = discord.Embed(title="🛠️ Admin Update", color=discord.Color.orange())
    embed.add_field(name="Member", value=member.mention, inline=False)
    embed.add_field(name="Added", value=amount, inline=False)
    embed.add_field(name="Total Rites", value=user["rites"], inline=False)
    embed.add_field(name="Gene Seeds", value=user["gene"], inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="approve_challenge", description="Officer approval for challenge completion")
@app_commands.choices(challenge=CHALLENGE_CHOICES)
async def approve_challenge(
    interaction: discord.Interaction,
    member: discord.Member,
    challenge: app_commands.Choice[str]
):
    # Permission check
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(
            "❌ You do not have permission.",
            ephemeral=True
        )

    await interaction.response.defer()

    uid = str(member.id)
    user = get_user(member.id)

    challenge_name = challenge.value

    # Already completed check
    if challenge_name in user["completed_challenges"]:
        return await interaction.followup.send("Already completed.")

    # Add challenge
    user["completed_challenges"].append(challenge_name)

    # Give role if mapped
    role_name = CHALLENGE_TO_RANK.get(challenge_name)
    if role_name:
        role = discord.utils.get(member.guild.roles, name=role_name)
        if role:
            await member.add_roles(role)

    # Save to SQLite
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE members
        SET completed_challenges = ?
        WHERE user_id = ?
    """, (
        json.dumps(user["completed_challenges"]),
        uid
    ))

    conn.commit()
    conn.close()

    await interaction.followup.send(
        f"✅ {member.mention} has completed **{challenge_name}** and been approved."
    )
# ==================================================
# PLAYER CARD
# ==================================================

@bot.tree.command(name="player_card")
async def player_card(interaction: discord.Interaction, member: discord.Member = None):
    await interaction.response.defer()  # 🔥 FIX
    member = member or interaction.user
    
    user = get_user(member.id)
    
    rites = user["rites"]
    gene = user["gene"]

    days = get_member_days(member)

    embed = discord.Embed(title="🪪 Service Record", color=discord.Color.purple())
    embed.set_thumbnail(url=member.display_avatar.url)

    rank = get_rank_with_time(member, rites)
    completed = user.get("completed_challenges", [])

    emoji_display = ""
    for rank_name in CHALLENGES.keys():
        if rank_name in completed:
            emoji_display += CHALLENGES[rank_name]["emoji"] + " "

    embed.add_field(name="Rank", value=f"{rank} {emoji_display}", inline=False)
    embed.add_field(name="Total Rites", value=rites, inline=False)
    embed.add_field(name="Gene Seeds Found", value=gene, inline=False)
    embed.add_field(name="Time in Chapter", value=f"{days} days", inline=False)

    relic_list = user.get("relics", [])
    relic_display = "\n".join(relic_list) if relic_list else "None"

    embed.add_field(name="Relics Earned", value=relic_display, inline=False)
    embed.add_field(name="Progress", value=get_progress_text(rites), inline=False)

    await interaction.followup.send(embed=embed)

# ==================================================
# OPERATION REPORT
# ==================================================
@bot.tree.command(name="operation_report")
@battle_reports_only()
@app_commands.choices(
    mission=MISSION_CHOICES,
    difficulty=OPERATION_DIFFICULTY_CHOICES,
    gene_seed=GENE_CHOICES
)
async def operation_report(
    interaction: discord.Interaction,
    mission: app_commands.Choice[str],
    difficulty: app_commands.Choice[str],
    gene_seed: app_commands.Choice[str],
    member1: discord.Member,
    screenshot1: discord.Attachment,
    screenshot2: discord.Attachment,
    member2: discord.Member = None,
    member3: discord.Member = None,
    screenshot3: discord.Attachment = None,
    screenshot4: discord.Attachment = None
):

    await safe_defer(interaction)
    
    base = OPERATION_DIFFICULTY[difficulty.value]
    gene_bonus = 1 if gene_seed.value == "Found" else 0
    total_rites = (base + gene_bonus) * (2 if event_active else 1)

    members = build_members(member1, member2, member3)
    lines = []

    for m in members:
        user = await add_rites(m, total_rites, gene_bonus)
        rites = user["rites"]
        gene = user["gene"]

        await update_rank_cached(member=m, user=user)
        new_relics = await check_relics_cached(member=m, user=user)

        if new_relics:
            await interaction.channel.send(
                f"🏆 {m.mention} has unlocked relic(s):\n"
                + "\n".join([f"⚜ {r}" for r in new_relics])
            )

        lines.append(
            f"{m.mention}\nTotal: {rites}\n{get_progress_text(rites)}"
        )

    embed = discord.Embed(title="⚔️ Operation Report", color=discord.Color.red())
    embed.add_field(name="Mission", value=mission.value, inline=False)
    embed.add_field(name="Difficulty", value=f"{difficulty.value} (+{base} Rites)", inline=False)

    gene_text = "Found (+1 Rites)" if gene_seed.value == "Found" else "None"
    embed.add_field(name="Gene Seed", value=gene_text, inline=False)
    embed.add_field(name="Members", value="\n\n".join(lines), inline=False)

    screenshots = [screenshot1, screenshot2, screenshot3, screenshot4]
    screenshots = [s for s in screenshots if s]

    await send_gallery(interaction, embed, screenshots,
        "The daemons are banished! Your willpower remains strong as steel. "
        "Let us ensure your tools are equally resolute."
    )

# ==================================================
# STRATAGEM REPORT
# ==================================================

@bot.tree.command(name="stratagem_report")
@battle_reports_only()
@app_commands.choices(
    mission=MISSION_CHOICES,
    difficulty=STRATAGEM_DIFFICULTY_CHOICES,
    gene_seed=GENE_CHOICES
)
async def stratagem_report(
    interaction: discord.Interaction,
    mission: app_commands.Choice[str],
    difficulty: app_commands.Choice[str],
    gene_seed: app_commands.Choice[str],
    member1: discord.Member,
    screenshot1: discord.Attachment,
    screenshot2: discord.Attachment,
    member2: discord.Member = None,
    member3: discord.Member = None,
    screenshot3: discord.Attachment = None,
    screenshot4: discord.Attachment = None
):

    await safe_defer(interaction)

    base = STRATAGEM_DIFFICULTY[difficulty.value]
    gene_bonus = 1 if gene_seed.value == "Found" else 0
    total_rites = (base + gene_bonus) * (2 if event_active else 1)

    difficulty_text = f"{difficulty.value} (+{base} Rites)"

    members = build_members(member1, member2, member3)

    lines = []

    for m in members:
        user = await add_rites(m, total_rites, gene_bonus)
        rites = user["rites"]
        gene = user["gene"]

        await update_rank_cached(member=m, user=user)
        new_relics = await check_relics_cached(member=m, user=user)

        if new_relics:
            await interaction.channel.send(
                f"🏆 {m.mention} has unlocked relic(s):\n"
                + "\n".join([f"⚜ {r}" for r in new_relics])
                )

        lines.append(
            f"{m.mention}\nTotal: {rites}\n{get_progress_text(rites)}"
        )

    embed = discord.Embed(title="⚔️ Stratagem Report", color=discord.Color.gold())
    embed.add_field(name="Mission", value=mission.value, inline=False)
    embed.add_field(name="Difficulty", value=difficulty_text, inline=False)

    gene_text = "Found (+1 Rites)" if gene_seed.value == "Found" else "None"
    embed.add_field(name="Gene Seed", value=gene_text, inline=False)

    embed.add_field(name="Members", value="\n\n".join(lines), inline=False)

    screenshots = [screenshot1, screenshot2, screenshot3, screenshot4]
    screenshots = [s for s in screenshots if s]

    await send_gallery(interaction, embed, screenshots,
        "...binaric whirring..."
        "[EXORCISM] protocols completed. The warp-taint is removed. "
        "Your wargear is sanctified."
    )
# ==================================================
# SIEGE REPORT
# ==================================================

@bot.tree.command(name="siege_report")
@battle_reports_only()
@app_commands.choices(waves=WAVE_CHOICES)
async def siege_report(interaction: discord.Interaction,
    waves: app_commands.Choice[int],
    member1: discord.Member,
    screenshot1: discord.Attachment,
    screenshot2: discord.Attachment,
    member2: discord.Member = None,
    member3: discord.Member = None,
    screenshot3: discord.Attachment = None,
    screenshot4: discord.Attachment = None
):
    await safe_defer(interaction)
    
    rites = (waves.value // 5) * 2
    members = build_members(member1, member2, member3)
    lines = []

    for m in members:
        user = await add_rites(m, rites, 0)
        total = user["rites"]

        await update_rank_cached(member=m, user=user)
        new_relics = await check_relics_cached(member=m, user=user)

        if new_relics:
            await interaction.channel.send(
                f"🏆 {m.mention} has unlocked relic(s):\n" +
                "\n".join([f"⚜ {r}" for r in new_relics])
            )
        lines.append(f"{m.mention}\nTotal: {total}\n{get_progress_text(total)}")

    embed = discord.Embed(title="⚔️ Siege Report", color=discord.Color.blurple())
    embed.add_field(name="Waves Cleared", value=str(waves.value), inline=False)
    embed.add_field(name="Members", value="\n\n".join(lines), inline=False)

    screenshots = [screenshot1, screenshot2, screenshot3, screenshot4]
    screenshots = [s for s in screenshots if s]

    await send_gallery(interaction, embed, screenshots,
        "Mission efficiency: (97%). "
        "Daemonic presence: (0%). "
        "A satisfactory outcome, my Lord. "
        "Your flesh has proved to be a durable vessel."
    )

# ==================================================
# PVP REPORT
# ==================================================

@bot.tree.command(name="pvp_report")
@battle_reports_only()
@app_commands.choices(victory=VICTORY_CHOICES)
@app_commands.describe(
    mode="PvP mode (e.g. Arena, Siege, Skirmish)"
)
async def pvp_report(
    interaction: discord.Interaction,
    mode: str,
    victory: app_commands.Choice[str],
    member1: discord.Member,
    screenshot1: discord.Attachment,
    screenshot2: discord.Attachment,
    member2: discord.Member = None,
    member3: discord.Member = None,
    screenshot3: discord.Attachment = None,
    screenshot4: discord.Attachment = None
):
    await safe_defer(interaction)
    
    rites = 3 if victory.value == "Yes" else 0
    members = build_members(member1, member2, member3)

    embed = discord.Embed(title="⚔️ PvP Report", color=discord.Color.green())
    embed.add_field(name="Mode", value=mode, inline=False)
    embed.add_field(name="Victory", value=victory.value, inline=False)

    for m in members:
        user = await add_rites(m, rites, 0)

        total = user["rites"]

        await update_rank_cached(member=m, user=user)
        new_relics = await check_relics_cached(member=m, user=user)

        if new_relics:
            await interaction.channel.send(
                f"🏆 {m.mention} has unlocked relic(s):\n" +
                "\n".join([f"⚜ {r}" for r in new_relics])
            )
        embed.add_field(
            name=m.display_name,
            value=f"+{rites} Rites\nTotal: {total}\n{get_progress_text(total)}",
            inline=False
        )

    screenshots = [screenshot1, screenshot2, screenshot3, screenshot4]
    screenshots = [s for s in screenshots if s]

    await send_gallery(interaction, embed, screenshots,
        "... [Combat efficiency confirmed. Daemonium containment holding [IN PROGRESS]. Data-transfer complete.]"
    )

# ==================================================
# EXORSUITS REPORT
# ==================================================

@bot.tree.command(name="exorsuits", description="Log an Exorsuits match result")
@battle_reports_only()
@app_commands.choices(victory=VICTORY_CHOICES)
async def exorsuits(
    interaction: discord.Interaction,
    victory: app_commands.Choice[str],
    member1: discord.Member,
    screenshot1: discord.Attachment,
    screenshot2: discord.Attachment,
    member2: discord.Member = None,
    member3: discord.Member = None,
    member4: discord.Member = None,
    screenshot3: discord.Attachment = None,
    screenshot4: discord.Attachment = None
):
    await safe_defer(interaction)

    rites = 2 if victory.value == "Yes" else 0
    members = [m for m in [member1, member2, member3, member4] if m]

    embed = discord.Embed(title="⚔️ Exorsuits Report", color=discord.Color.teal())
    embed.add_field(name="Victory", value=victory.value, inline=False)

    for m in members:
        user = await add_rites(m, rites, 0)

        total = user["rites"]

        await update_rank_cached(member=m, user=user)
        new_relics = await check_relics_cached(member=m, user=user)

        if new_relics:
            await interaction.channel.send(
                f"🏆 {m.mention} has unlocked relic(s):\n" +
                "\n".join([f"⚜ {r}" for r in new_relics])
            )
        embed.add_field(
            name=m.display_name,
            value=f"+{rites} Rites\nTotal: {total}\n{get_progress_text(total)}",
            inline=False
        )

    screenshots = [screenshot1, screenshot2, screenshot3, screenshot4]
    screenshots = [s for s in screenshots if s]

    await send_gallery(interaction, embed, screenshots,
        "...Divine Liberty has been dispersed. Amplifing orbital combat systems..."
    )

# ==================================================
# READY
# ==================================================
@bot.tree.command(name="event_request", description="Submit an event idea for approval")
@app_commands.describe(details="Describe your event idea in detail")
async def event_request(interaction: discord.Interaction, details: str):

    embed = discord.Embed(
        title="✏️Event Request",
        description=details,
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(name="Requested By", value=interaction.user.mention, inline=False)

    await interaction.response.send_message(
        "📨 Your event request has been submitted for review.",
        ephemeral=True
    )

    await interaction.channel.send(
        embed=embed,
        view=EventApprovalView()
    )

@bot.tree.command(name="relic_progress", description="View relic unlock progression for a member")
@techsorcist_records_only()
async def relic_progress(interaction: discord.Interaction, member: discord.Member = None):

    member = member or interaction.user

    user = get_user(member.id)

    rites = user["rites"]
    gene = user["gene"]
    unlocked = user.get("relics", [])

    embed = discord.Embed(
        title="🧬 Relic Progression",
        description=f"Tracking relic unlock status for **{member.display_name}**",
        color=discord.Color.dark_purple()
    )

    for relic, req in RELICS.items():
        status = "✅ UNLOCKED" if relic in unlocked else "🔒 LOCKED"

        embed.add_field(
            name=f"{relic} — {status}",
            value=f"Gene Seeds: {gene}/{req['gene']}\nRites: {rites}/{req['rites']}",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(
    name="challenge_progress",
    description="View challenge progression for a member"
)
@techsorcist_records_only()
async def challenge_progress(interaction: discord.Interaction, member: discord.Member = None):

    member = member or interaction.user

    user = get_user(member.id)
    
    rites = user["rites"]
    completed = user.get("completed_challenges", [])

    days = get_member_days(member)

    embed = discord.Embed(
        title="📜 Challenge Progression",
        description=f"Tracking challenge status for **{member.display_name}**",
        color=discord.Color.dark_gold()
    )

    for challenge_name, req in CHALLENGE_REQUIREMENTS.items():

        emoji = CHALLENGES.get(challenge_name, {}).get("emoji", "")
        auto = CHALLENGES.get(challenge_name, {}).get("auto", False)

        status = "🔒 Locked"
        if challenge_name in completed:
            status = "✅ Completed"

        # -------------------------
        # REQUIREMENT BUILD
        # -------------------------
        lines = []

        if "rites" in req:
            lines.append(f"Rites: {rites}/{req['rites']}")

        if "days" in req:
            lines.append(f"Time: {days}/{req['days']} days")

        if req.get("approval"):
            lines.append("Officer Approval Required")

        if "special" in req:
            lines.append(f"⚠ {req['special']}")

        # -------------------------
        # DEPENDENCY CHECKS
        # -------------------------

        if challenge_name == "Enochian Guard":
            if "Veteran" not in completed:
                status = "🔒 Locked (Requires Veteran)"

        if challenge_name == "Daemonium Palatinae":
            if "Enochian Guard" not in completed:
                status = "🔒 Locked (Requires Enochian Guard)"

        # -------------------------
        # FINAL DISPLAY
        # -------------------------

        embed.add_field(
            name=f"{emoji} {challenge_name} — {status}",
            value=f"Type: {'Auto' if auto else 'Officer Approval'}\n"
                  + ("\n".join(lines) if lines else "No requirements listed"),
            inline=False
        )

    await interaction.response.send_message(embed=embed)

synced = False

await bot.tree.sync()
print("FORCED SYNC DONE")

@bot.event
async def on_member_join(member):
    try:
        channel = bot.get_channel(1393664184771936279)

        await channel.send(
            f"... **INITIATE DETECTED** ...\n\n"
            f"Welcome to Banish, home of the Exorcists!\n"
            f"I am the Techsorcist, keeper of your records.\n\n"
            f"Proceed to the Halls of Tempering to begin your trials, {member.mention}."
        )

    except Exception as e:
        print(f"on_member_join failed: {e}")

bot.run(TOKEN)
    
