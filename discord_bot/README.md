# 🤖 Luqqzstrap Discord Bot & Backend Server

Este diretório contém o servidor Backend API e o Bot do Discord para integração oficial com o **Luqqzstrap App**.

## 🚀 Como Executar

### 1. Instalar Dependências
```bash
pip install discord.py aiohttp
```

### 2. Configurar Token do Bot
No portal de desenvolvedores do Discord ([Discord Developer Portal](https://discord.com/developers/applications)):
1. Crie uma nova aplicação e adicione um **Bot**.
2. Ative as Intents necessárias (**Bot Intents**).
3. Copie o **Token do Bot**.

### 3. Iniciar o Servidor & Bot
No terminal ou no seu provedor de hospedagem (Render, Railway, VPS, etc.):
```bash
export DISCORD_BOT_TOKEN="seu_token_aqui"
export PORT=8000
python bot_server.py
```
*(No Windows PowerShell: `$env:DISCORD_BOT_TOKEN="seu_token_aqui"; python bot_server.py`)*

---

## 📡 Endpoints da API HTTP

- `POST /api/v1/link/verify`: Valida o código de 6 dígitos inserido no app desktop e retorna o `auth_token`.
- `POST /api/v1/heartbeat`: Recebe as FastFlags, informações do Roblox e status do Luqqzstrap em tempo real.
- `POST /api/v1/updates/announce`: Dispara um anúncio instantâneo de atualização com Components V2 via webhook ou CI/CD.

---

## 🤖 Comandos Slash no Discord

### 📢 Notificações de Atualizações (Admin)
- `/config_updates [canal] [mencao] [cargo]`: Configura o canal de anúncios e tipo de menção (@everyone, @here, cargo ou sem menção).
- `/testar_anuncio`: Envia uma mensagem de teste no canal configurado com botões interativos (Components V2).
- `/anunciar_update`: Força o anúncio manual da versão mais recente do Luqqzstrap presente no GitHub.

### 🎮 Integração com o Jogador
- `/vincular`: Gera o código de 6 dígitos (`LQZ-XXXXXX`) para o usuário parear o aplicativo no PC.
- `/desvincular`: Remove a conexão da conta do Discord.
- `/status [@usuario]`: Exibe o jogo atual do Roblox, botão para entrar no servidor (`job_id`), preset ativo, FPS e quantidade de FFlags.
- `/flags [@usuario]`: Exibe a prévia e anexa o arquivo `fflags.json` com todas as FastFlags ativas do usuário.
