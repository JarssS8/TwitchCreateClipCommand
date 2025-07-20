import os
import socket
import asyncio
import aiohttp
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

HOST = 'irc.chat.twitch.tv'
PORT = 6667
TOKEN = os.getenv('TWITCH_OAUTH_TOKEN')
CHANNEL = os.getenv('TWITCH_CHANNEL')
CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
BROADCASTER_ID = os.getenv('TWITCH_BROADCASTER_ID')  # Añadir el broadcaster ID
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

def send_message(sock, message):
    sock.send(f'PRIVMSG #{CHANNEL} :{message}\r\n'.encode('utf-8'))

async def send_clip_to_discord(clip_url, channel_name, clip_data=None):
    """Envía el clip al webhook de Discord"""
    try:
        # Información básica del embed
        embed = {
            "title": "🎬 Nuevo Clip Creado!",
            "description": f"Se ha creado un nuevo clip en el canal **{channel_name}**",
            "url": clip_url,
            "color": 0x9146FF,  # Color morado de Twitch
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Si tenemos datos del clip, agregar más información
        if clip_data:
            # Título del clip si está disponible
            if clip_data.get('title'):
                embed["title"] = f"🎬 {clip_data['title']}"
            
            # Descripción más detallada
            embed["description"] = f"Nuevo clip creado en **{channel_name}**"
            
            # Miniatura del clip
            if clip_data.get('thumbnail_url'):
                embed["thumbnail"] = {
                    "url": clip_data['thumbnail_url']
                }
            
            # Campos con información adicional
            fields = [
                {
                    "name": "🔗 Link del Clip",
                    "value": f"[Ver Clip]({clip_url})",
                    "inline": True
                },
                {
                    "name": "✏️ Editar Clip",
                    "value": f"[Editar]({clip_url}/edit)",
                    "inline": True
                }
            ]
            
            # Duración del clip
            if clip_data.get('duration'):
                fields.append({
                    "name": "⏱️ Duración",
                    "value": f"{clip_data['duration']} segundos",
                    "inline": True
                })
            
            # Número de vistas (será 0 al principio)
            if 'view_count' in clip_data:
                fields.append({
                    "name": "👀 Vistas",
                    "value": str(clip_data['view_count']),
                    "inline": True
                })
            
            # Creador del clip
            if clip_data.get('creator_name'):
                fields.append({
                    "name": "👤 Creado por",
                    "value": clip_data['creator_name'],
                    "inline": True
                })
            
            # Fecha de creación
            if clip_data.get('created_at'):
                created_time = datetime.fromisoformat(clip_data['created_at'].replace('Z', '+00:00'))
                fields.append({
                    "name": "📅 Creado",
                    "value": created_time.strftime("%d/%m/%Y %H:%M UTC"),
                    "inline": True
                })
            
            # ID del clip para referencia
            if clip_data.get('id'):
                fields.append({
                    "name": "🆔 ID del Clip",
                    "value": f"`{clip_data['id']}`",
                    "inline": True
                })
            
            embed["fields"] = fields
        else:
            # Fallback si no hay datos adicionales
            embed["fields"] = [
                {
                    "name": "🔗 Link del Clip",
                    "value": f"[Ver Clip]({clip_url})",
                    "inline": False
                }
            ]
        
        # Footer con información del bot
        embed["footer"] = {
            "text": "Lore Clipper Bot • Twitch Clips",
            "icon_url": "https://static-cdn.jtvnw.net/jtv_user_pictures/8a6381c7-d0c0-4576-b179-38bd5ce1d6af-profile_image-70x70.png"
        }
        
        payload = {
            "embeds": [embed]
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(DISCORD_WEBHOOK_URL, json=payload) as response:
                if response.status == 204:
                    print("✅ Clip enviado a Discord exitosamente", flush=True)
                else:
                    error_text = await response.text()
                    print(f"❌ Error al enviar a Discord: {response.status} - {error_text}", flush=True)
    except Exception as e:
        print(f"❌ Error al enviar clip a Discord: {e}", flush=True)

async def get_clip_details(clip_id):
    """Obtiene información detallada del clip desde la API de Twitch"""
    try:
        url = f"https://api.twitch.tv/helix/clips?id={clip_id}"
        
        oauth_token = TOKEN.replace('oauth:', '') if TOKEN else None
        headers = {
            'Authorization': f'Bearer {oauth_token}',
            'Client-Id': CLIENT_ID
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('data') and len(data['data']) > 0:
                        return data['data'][0]
                    else:
                        print("❌ No se encontraron detalles del clip", flush=True)
                        return None
                else:
                    error_text = await response.text()
                    print(f"❌ Error al obtener detalles del clip: {response.status} - {error_text}", flush=True)
                    return None
                    
    except Exception as e:
        print(f"❌ Error al obtener detalles del clip: {e}", flush=True)
        return None

def extract_username_from_message(message):
    """Extrae el nombre de usuario del mensaje de Twitch IRC"""
    try:
        # Formato: :username!username@username.tmi.twitch.tv PRIVMSG #channel :!clip
        if ':' in message and '!' in message:
            username = message.split(':')[1].split('!')[0]
            return username
        return None
    except:
        return None

async def create_clip(creator_username=None, clip_name=None):
    try:
        # Prepare the API request
        url = f"https://api.twitch.tv/helix/clips?broadcaster_id={BROADCASTER_ID}&duration=60"
        
        # Remove 'oauth:' prefix if present
        oauth_token = TOKEN.replace('oauth:', '') if TOKEN else None
        
        if not oauth_token:
            raise Exception("No se encontró TWITCH_OAUTH_TOKEN en el archivo .env")
        
        headers = {
            'Authorization': f'Bearer {oauth_token}',
            'Client-Id': CLIENT_ID
        }
        
        print(f"🎬 Creando clip para {CHANNEL} con duración de 60 segundos...", flush=True)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                if response.status == 202:  # Twitch returns 202 for successful clip creation
                    data = await response.json()                      
                    if data.get('data') and len(data['data']) > 0:
                        clip_id = data['data'][0]['id']
                        # Return URL without /edit
                        clip_url = f"https://clips.twitch.tv/{clip_id}"
                        print(f"✅ Clip creado: {clip_url}", flush=True)
                        
                        # Obtener detalles adicionales del clip
                        print("📋 Obteniendo detalles del clip...", flush=True)
                        clip_details = await get_clip_details(clip_id)
                        
                        # Agregar el nombre del creador desde el chat si está disponible
                        if creator_username and clip_details:
                            clip_details['creator_name'] = creator_username
                        elif creator_username:
                            # Si no hay clip_details, crear un diccionario básico
                            clip_details = {'creator_name': creator_username}
                        if clip_name:
                            clip_details['title'] = clip_name
                        # Enviar clip a Discord con información detallada
                        await send_clip_to_discord(clip_url, CHANNEL, clip_details)
                        
                        return clip_url
                    else:
                        raise Exception("No se recibieron datos del clip")
                else:
                    error_text = await response.text()
                    raise Exception(f"Error en la API: {response.status} - {error_text}")
                    
    except Exception as e:
        raise e

async def bot_loop():
    sock = socket.socket()
    sock.connect((HOST, PORT))
    sock.send(f"PASS {TOKEN}\r\n".encode('utf-8'))
    sock.send(f"NICK {CHANNEL}\r\n".encode('utf-8'))
    sock.send(f"JOIN #{CHANNEL}\r\n".encode('utf-8'))

    while True:
        resp = sock.recv(2048).decode('utf-8')

        if resp.startswith('PING'):
            sock.send("PONG :tmi.twitch.tv\r\n".encode('utf-8'))        
        elif '!clip' in resp:
            print("Comando !clip recibido", flush=True)
            clip_name = resp.split('!clip')[1].strip()
            # Extraer el nombre de usuario que ejecutó el comando
            creator_username = extract_username_from_message(resp)
            if creator_username:
                print(f"👤 Comando ejecutado por: {creator_username}", flush=True)
            
            try:
                clip_url = await create_clip(creator_username, clip_name)
                if not clip_name:
                    clip_name = "Clip creado"
                send_message(sock, f"📸 {clip_name}: {clip_url}")
            except Exception as e:
                print(f"Error al crear clip: {e}", flush=True)
                send_message(sock, "❌ Error al crear el clip. Inténtalo más tarde.")

if __name__ == '__main__':
    asyncio.run(bot_loop())
