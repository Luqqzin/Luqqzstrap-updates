import os
import sys
import time
import uuid
import random
import string
import json
import asyncio
from typing import Dict, Any, Optional

try:
    import discord
    from discord import app_commands
    from discord.ext import commands, tasks
    from aiohttp import web
    import aiohttp
except ImportError:
    print("[!] Dependências não encontradas. Instale com: pip install discord.py aiohttp")
    sys.exit(1)

# ─── Configurações Gerais do Servidor & Bot ───
PORT = int(os.environ.get("PORT", 8000))
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_config.json")
LATEST_JSON_URL = "https://raw.githubusercontent.com/Luqqzin/Luqqzstrap-updates/main/latest.json"

# ─── Gerenciador de Configuração Persistente ───
def load_config() -> Dict[str, Any]:
    default_config = {
        "channel_id": int(os.environ.get("UPDATE_CHANNEL_ID", 0)) or None,
        "mention_type": os.environ.get("UPDATE_MENTION_TYPE", "everyone"),  # 'everyone', 'here', 'role', 'none'
        "role_id": int(os.environ.get("UPDATE_ROLE_ID", 0)) or None,
        "check_interval_minutes": 3,
        "last_announced_version": None,
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_config.update(saved)
        except Exception as e:
            print(f"[!] Erro ao carregar {CONFIG_FILE}: {e}")
    return default_config

def save_config(cfg: Dict[str, Any]):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Erro ao salvar {CONFIG_FILE}: {e}")

bot_config = load_config()

# Armazenamento em memória para vinculação e presença
linking_codes: Dict[str, Dict[str, Any]] = {}  # code -> {user_id, username, created_at}
user_tokens: Dict[str, str] = {}  # token -> discord_user_id
discord_to_tokens: Dict[str, str] = {}  # discord_user_id -> token
user_presence: Dict[str, Dict[str, Any]] = {}  # discord_user_id -> {last_seen, payload}

def generate_code(length=6) -> str:
    return 'LQZ-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


# ─── Discord UI Components V2 (ActionRows & Interactive Buttons) ───

class UpdateReleaseView(discord.ui.View):
    """Componentes V2 do Discord com botões de ação e links diretos."""
    def __init__(self, download_url: str, zip_url: str = "", release_url: str = ""):
        super().__init__(timeout=None)

        if download_url:
            self.add_item(discord.ui.Button(
                label="Baixar Instalador (.exe)",
                style=discord.ButtonStyle.link,
                url=download_url,
                emoji="⚡"
            ))

        if zip_url:
            self.add_item(discord.ui.Button(
                label="Download Portátil (.zip)",
                style=discord.ButtonStyle.link,
                url=zip_url,
                emoji="📦"
            ))

        self.add_item(discord.ui.Button(
            label="Ver no GitHub",
            style=discord.ButtonStyle.link,
            url=release_url or "https://github.com/Luqqzin/Luqqzstrap/releases",
            emoji="🔗"
        ))


# ─── Função de Envio de Anúncio de Atualizações ───

async def send_update_announcement(data: Dict[str, Any], is_test: bool = False) -> bool:
    """Envia o anúncio formatado com Components V2 no canal configurado."""
    channel_id = bot_config.get("channel_id")
    if not channel_id:
        print("[!] Nenhum canal de anúncio configurado. Use /config_updates no Discord.")
        return False

    channel = bot.get_channel(int(channel_id))
    if not channel:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except Exception:
            channel = None

    if not channel:
        print(f"[!] Canal de anúncio ID {channel_id} não encontrado no Discord.")
        return False

    version = str(data.get("version", "Nova Versão")).strip()
    tag_name = str(data.get("tag_name", f"v{version}" if not version.startswith("v") else version)).strip()
    download_url = data.get("download_url") or "https://github.com/Luqqzin/Luqqzstrap-updates/releases/latest/download/Luqqzstrap_Setup.exe"
    zip_url = data.get("zip_url") or "https://github.com/Luqqzin/Luqqzstrap-updates/releases/latest/download/Luqqzstrap-windows.zip"
    release_url = data.get("release_url") or f"https://github.com/Luqqzin/Luqqzstrap/releases/tag/{tag_name}"
    changelog = data.get("changelog") or "Melhorias de desempenho, suporte a novas versões e correções gerais."

    # Configuração de Menção
    mtype = bot_config.get("mention_type", "everyone")
    role_id = bot_config.get("role_id")

    mention_text = ""
    if mtype == "everyone":
        mention_text = "@everyone"
    elif mtype == "here":
        mention_text = "@here"
    elif mtype == "role" and role_id:
        mention_text = f"<@&{role_id}>"

    header = "🧪 **[TESTE DE ANÚNCIO - PRÉVIA]**" if is_test else "📢 **NOVA ATUALIZAÇÃO DISPONÍVEL DO LUQQZSTRAP!**"
    content_message = f"{header} {mention_text}".strip()

    # Montagem do Embed Principal
    embed = discord.Embed(
        title=f"🚀 Luqqzstrap {tag_name} Lançado!",
        description=(
            f"Uma nova versão oficial do **Luqqzstrap** já está disponível para atualização!\n\n"
            f"### 📋 O que há de novo nesta versão:\n{changelog}\n\n"
            f"Utilize os botões abaixo para baixar o instalador universal ou obter o pacote portátil."
        ),
        color=discord.Color.from_rgb(239, 35, 60),  # Tema Vermelho Luqqzstrap (#ef233c)
        url=release_url
    )
    
    embed.set_thumbnail(url="https://raw.githubusercontent.com/Luqqzin/Luqqzstrap/main/src/gui/ui/luqqzstrap_logo.png")
    embed.set_footer(
        text="Luqqzstrap Auto-Updater • Notificação Oficial",
        icon_url="https://raw.githubusercontent.com/Luqqzin/Luqqzstrap/main/src/gui/ui/luqqzstrap_logo.png"
    )

    # Criação dos Components V2 (ActionRow com Botões)
    view = UpdateReleaseView(download_url=download_url, zip_url=zip_url, release_url=release_url)

    try:
        await channel.send(content=content_message, embed=embed, view=view)
        print(f"[+] Anúncio da versão {tag_name} enviado com sucesso para o canal #{channel.name} ({channel.id})")
        return True
    except Exception as e:
        print(f"[!] Falha ao enviar mensagem de update no Discord: {e}")
        return False


# ─── Tarefa em Segundo Plano de Monitoramento de Updates ───

@tasks.loop(minutes=3)
async def check_for_updates_task():
    """Verifica periodicamente o latest.json no GitHub para anunciar novos releases."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(LATEST_JSON_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    current_version = str(data.get("version", "")).strip()

                    last_ver = bot_config.get("last_announced_version")

                    # Primeira inicialização: grava a versão atual para evitar anúncio duplicado no reboot
                    if last_ver is None:
                        bot_config["last_announced_version"] = current_version
                        save_config(bot_config)
                        print(f"[*] Monitor de updates iniciado. Versão base memorizada: {current_version}")
                        return

                    # Se a versão mudou, dispara o anúncio automático
                    if current_version and current_version != last_ver:
                        print(f"[+] Novo release detectado: {last_ver} -> {current_version}")
                        success = await send_update_announcement(data, is_test=False)
                        if success:
                            bot_config["last_announced_version"] = current_version
                            save_config(bot_config)
    except Exception as e:
        print(f"[!] Erro no loop de verificação de updates: {e}")

@check_for_updates_task.before_loop
async def before_check_for_updates():
    await bot.wait_until_ready()


# ─── API HTTP Webserver (aiohttp) ───

async def handle_verify_link(request: web.Request):
    """Endpoint chamado pelo Luqqzstrap App para validar o código gerado no Discord."""
    try:
        data = await request.json()
        code = str(data.get("code", "")).strip().upper()
        
        if code not in linking_codes:
            return web.json_response({"success": False, "error": "Código inválido ou expirado."})
            
        info = linking_codes.pop(code)
        if time.time() - info["created_at"] > 600:
            return web.json_response({"success": False, "error": "Código expirou."})
            
        discord_id = info["user_id"]
        username = info["username"]
        
        token = str(uuid.uuid4())
        user_tokens[token] = discord_id
        discord_to_tokens[discord_id] = token
        
        print(f"[+] Conta pareada com sucesso! Discord User: {username} ({discord_id})")
        return web.json_response({
            "success": True,
            "auth_token": token,
            "username": username
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def handle_heartbeat(request: web.Request):
    """Endpoint chamado periodicamente pelo Luqqzstrap App para atualizar status."""
    try:
        data = await request.json()
        token = data.get("auth_token")
        
        if not token or token not in user_tokens:
            return web.json_response({"success": False, "error": "Não autorizado."}, status=401)
            
        discord_id = user_tokens[token]
        user_presence[discord_id] = {
            "last_seen": time.time(),
            "payload": data
        }
        
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def handle_manual_announce_webhook(request: web.Request):
    """Webhook HTTP para disparar anúncio instantâneo via GitHub Actions ou CI/CD."""
    try:
        data = await request.json()
        success = await send_update_announcement(data, is_test=False)
        if success:
            bot_config["last_announced_version"] = str(data.get("version", "")).strip()
            save_config(bot_config)
            return web.json_response({"success": True, "message": "Anúncio publicado com sucesso no Discord!"})
        else:
            return web.json_response({"success": False, "error": "Falha ao enviar mensagem no canal configurado."}, status=400)
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def start_web_server():
    app = web.Application()
    app.router.add_post('/api/v1/link/verify', handle_verify_link)
    app.router.add_post('/api/v1/heartbeat', handle_heartbeat)
    app.router.add_post('/api/v1/updates/announce', handle_manual_announce_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"[+] API HTTP do Luqqzstrap rodando na porta {PORT}", flush=True)


# ─── Bot do Discord & Comandos Slash ───

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"[+] Bot online como {bot.user}", flush=True)
    try:
        synced = await bot.tree.sync()
        print(f"[+] Sincronizados {len(synced)} comandos Slash.", flush=True)
    except Exception as e:
        print(f"[!] Erro ao sincronizar comandos Slash: {e}", flush=True)

    if not check_for_updates_task.is_running():
        check_for_updates_task.start()
        print("[+] Monitor de novos releases do Luqqzstrap ativado.", flush=True)

@bot.tree.command(name="config_updates", description="Configura o canal e menções para anúncios automáticos de updates")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    canal="Canal de texto onde os anúncios de atualização serão postados",
    mencao="Tipo de menção ao anunciar o update",
    cargo="Cargo específico para menção (apenas se selecionou 'Cargo Específico')"
)
@app_commands.choices(mencao=[
    app_commands.Choice(name="📢 Mencionar @everyone", value="everyone"),
    app_commands.Choice(name="🔔 Mencionar @here", value="here"),
    app_commands.Choice(name="👥 Mencionar Cargo Específico", value="role"),
    app_commands.Choice(name="🔕 Sem Menção (Apenas mensagem)", value="none")
])
async def cmd_config_updates(
    interaction: discord.Interaction, 
    canal: discord.TextChannel, 
    mencao: app_commands.Choice[str], 
    cargo: discord.Role = None
):
    if mencao.value == "role" and not cargo:
        await interaction.response.send_message("⚠️ Você selecionou 'Cargo Específico', então precisa escolher qual é o cargo no campo `cargo`!", ephemeral=True)
        return

    bot_config["channel_id"] = canal.id
    bot_config["mention_type"] = mencao.value
    bot_config["role_id"] = cargo.id if cargo else None
    save_config(bot_config)

    mention_str = "@everyone" if mencao.value == "everyone" else "@here" if mencao.value == "here" else cargo.mention if cargo else "Nenhuma"

    embed = discord.Embed(
        title="⚙️ Configurações de Anúncios Salvas!",
        description=(
            f"O sistema de auto-atualização do **Luqqzstrap** foi configurado com sucesso:\n\n"
            f"• **Canal de Anúncios:** {canal.mention}\n"
            f"• **Notificação:** `{mention_str}`\n\n"
            f"💡 *Sempre que uma nova versão sair no GitHub, o bot anunciará automaticamente com botões de download direto!*\n"
            f"Você pode testar o visual usando o comando `/testar_anuncio`."
        ),
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="testar_anuncio", description="Envia uma prévia do anúncio de atualização para testar o visual")
@app_commands.default_permissions(administrator=True)
async def cmd_testar_anuncio(interaction: discord.Interaction):
    if not bot_config.get("channel_id"):
        await interaction.response.send_message("⚠️ Nenhum canal foi configurado ainda. Use `/config_updates` primeiro.", ephemeral=True)
        return

    await interaction.response.send_message("🔄 Enviando prévia do anúncio para o canal configurado...", ephemeral=True)

    sample_data = {
        "version": "2.7.3-beta",
        "tag_name": "v2.7.3-beta",
        "changelog": (
            "• **⚡ Native PE FastFlag Dumper:** Gerador binário nativo ultra-rápido (0.9s)\n"
            "• **🔄 Roblox Version Changer:** Suporte oficial para a versão **v735.3** com Live Memory\n"
            "• **🎨 Interface & Usabilidade:** Layout responsivo nos controles e suporte ao atalho Enter"
        ),
        "download_url": "https://github.com/Luqqzin/Luqqzstrap-updates/releases/download/v2.7.3-beta/Luqqzstrap_Setup.exe",
        "zip_url": "https://github.com/Luqqzin/Luqqzstrap-updates/releases/download/v2.7.3-beta/Luqqzstrap-windows.zip",
        "release_url": "https://github.com/Luqqzin/Luqqzstrap/releases/tag/v2.7.3-beta"
    }
    await send_update_announcement(sample_data, is_test=True)

@bot.tree.command(name="anunciar_update", description="Força o anúncio manual da versão mais recente no GitHub")
@app_commands.default_permissions(administrator=True)
async def cmd_anunciar_update(interaction: discord.Interaction):
    if not bot_config.get("channel_id"):
        await interaction.response.send_message("⚠️ Nenhum canal foi configurado ainda. Use `/config_updates` primeiro.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(LATEST_JSON_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    success = await send_update_announcement(data, is_test=False)
                    if success:
                        bot_config["last_announced_version"] = str(data.get("version", "")).strip()
                        save_config(bot_config)
                        await interaction.followup.send("✅ Anúncio da versão oficial enviado com sucesso no canal configurado!", ephemeral=True)
                    else:
                        await interaction.followup.send("❌ Falha ao enviar a mensagem no canal.", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Erro ao consultar GitHub (Status {resp.status})", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Erro ao processar anúncio: {e}", ephemeral=True)

@bot.tree.command(name="vincular", description="Gera um código de 6 dígitos para conectar o Luqqzstrap App")
async def cmd_vincular(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    username = str(interaction.user)
    
    for code, info in list(linking_codes.items()):
        if info["user_id"] == user_id:
            linking_codes.pop(code, None)
            
    new_code = generate_code()
    linking_codes[new_code] = {
        "user_id": user_id,
        "username": username,
        "created_at": time.time()
    }
    
    embed = discord.Embed(
        title="🔗 Vinculação com o Luqqzstrap App",
        description=f"Seu código de vinculação único é:\n\n# `{new_code}`\n\nAbra o **Luqqzstrap** no seu PC -> **Configurações** -> **Integração Discord Bot** e insira este código.",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Este código é válido por 10 minutos.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="desvincular", description="Desconecta seu Luqqzstrap App da sua conta do Discord")
async def cmd_desvincular(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    token = discord_to_tokens.pop(user_id, None)
    if token:
        user_tokens.pop(token, None)
        user_presence.pop(user_id, None)
        await interaction.response.send_message("✅ Seu Luqqzstrap App foi desvinculado com sucesso!", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ Sua conta não possui nenhum aplicativo Luqqzstrap vinculado.", ephemeral=True)

@bot.tree.command(name="status", description="Exibe o status do Roblox e configurações do Luqqzstrap de um usuário")
@app_commands.describe(usuario="Usuário para consultar o status (deixe vazio para ver o seu)")
async def cmd_status(interaction: discord.Interaction, usuario: discord.User = None):
    target = usuario or interaction.user
    target_id = str(target.id)
    
    data_entry = user_presence.get(target_id)
    if not data_entry or (time.time() - data_entry["last_seen"] > 90):
        embed = discord.Embed(
            title=f"🎮 Status do Roblox - {target.display_name}",
            description="❌ **Offline / App Fechado**\nO usuário não está com o Luqqzstrap ativo ou não vinculou a conta.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        return

    payload = data_entry["payload"]
    roblox = payload.get("roblox", {})
    lq = payload.get("luqqzstrap", {})

    embed = discord.Embed(
        title=f"🎮 Status no Roblox — {target.display_name}",
        color=discord.Color.green() if roblox.get("is_running") else discord.Color.gold()
    )
    embed.set_thumbnail(url=target.display_avatar.url)

    if roblox.get("is_running"):
        game_name = roblox.get("game_name") or "Jogando Roblox"
        embed.add_field(name="🟢 Status", value=f"**{game_name}**", inline=False)
        
        place_id = roblox.get("place_id")
        job_id = roblox.get("job_id")
        if place_id and job_id:
            join_link = f"https://www.roblox.com/games/start?placeId={place_id}&gameInstanceId={job_id}"
            embed.add_field(name="🔗 Servidor Direto", value=f"[Entrar no Servidor do {target.display_name}]({join_link})", inline=False)
    else:
        embed.add_field(name="🟡 Status", value="Roblox Fechado (Luqqzstrap Aberto)", inline=False)

    flags_count = lq.get("active_fflags_count", 0)
    fps = lq.get("fps_limit", 240)
    font = lq.get("custom_font", "Padrão")
    version = payload.get("version", "v2.7.3-beta")

    details = f"• **Versão**: `v{version}`\n"
    details += f"• **Limite de FPS**: `{fps} FPS`\n"
    details += f"• **Fonte Customizada**: `{font}`\n"
    details += f"• **FastFlags Ativas**: `{flags_count} flags`\n"

    embed.add_field(name="⚙️ Configurações do Luqqzstrap", value=details, inline=False)
    embed.set_footer(text="Luqqzstrap Bot Integration • Atualizado em tempo real")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="flags", description="Lista e exporta as FastFlags ativas de um usuário")
@app_commands.describe(usuario="Usuário para consultar as FastFlags (deixe vazio para ver as suas)")
async def cmd_flags(interaction: discord.Interaction, usuario: discord.User = None):
    target = usuario or interaction.user
    target_id = str(target.id)
    
    data_entry = user_presence.get(target_id)
    if not data_entry or (time.time() - data_entry["last_seen"] > 90):
        await interaction.response.send_message(f"❌ {target.display_name} está offline no Luqqzstrap.", ephemeral=True)
        return

    payload = data_entry["payload"]
    privacy = payload.get("privacy", {})
    
    if not privacy.get("show_flags", True):
        await interaction.response.send_message(f"🔒 {target.display_name} optou por manter suas FastFlags privadas.", ephemeral=True)
        return

    lq = payload.get("luqqzstrap", {})
    flags = lq.get("active_fflags", {})

    if not flags:
        await interaction.response.send_message(f"ℹ️ {target.display_name} não possui FastFlags ativas no momento.", ephemeral=True)
        return

    flags_json_str = json.dumps(flags, indent=4)
    file_bytes = flags_json_str.encode('utf-8')
    
    from io import BytesIO
    fp = BytesIO(file_bytes)
    file = discord.File(fp, filename=f"fflags_{target.name}.json")

    embed = discord.Embed(
        title=f"🚩 FastFlags Ativas de {target.display_name}",
        description=f"Total de **{len(flags)} FastFlags** configuradas no Luqqzstrap.\nBaixe o arquivo `.json` em anexo para importar no seu próprio Luqqzstrap!",
        color=discord.Color.purple()
    )
    
    preview_items = list(flags.items())[:10]
    preview_text = "```json\n{\n" + ",\n".join([f'  "{k}": "{v}"' for k, v in preview_items])
    if len(flags) > 10:
        preview_text += f"\n  ... (+{len(flags) - 10} flags no arquivo anexado)"
    preview_text += "\n}\n```"

    embed.add_field(name="📋 Preview", value=preview_text, inline=False)
    
    await interaction.response.send_message(embed=embed, file=file)


# ─── Main Startup ───

async def main():
    await start_web_server()
    if not BOT_TOKEN or BOT_TOKEN == "SEU_DISCORD_BOT_TOKEN_AQUI":
        print("[!] ATENÇÃO: Defina a variável de ambiente DISCORD_BOT_TOKEN antes de iniciar o bot.")
        while True:
            await asyncio.sleep(3600)
    else:
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[+] Servidor finalizado com sucesso.")
