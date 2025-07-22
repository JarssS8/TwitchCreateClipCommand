import socket
import requests
import threading
import time
import logging
import os
import sys
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

REQUIRED_ENV_VARS = ['BOT_USERNAME', 'OAUTH_TOKEN', 'CHANNEL_NAME', 'CLIENT_ID', 'ACCESS_TOKEN', 'CLIP_COOLDOWN_SECONDS', 'RECONNECT_DELAY_SECONDS', 'DISCORD_WEBHOOK_URL']
for var in REQUIRED_ENV_VARS:
    if not os.getenv(var):
        logging.critical(f"Error: La variable de entorno '{var}' no está configurada. Por favor, añádela a tu archivo .env.")
        sys.exit(1)

HOST = 'irc.chat.twitch.tv'
PORT = 6667
NICK = os.getenv('BOT_USERNAME')
TOKEN = os.getenv('OAUTH_TOKEN')
CHANNEL = f"#{os.getenv('CHANNEL_NAME')}"
CLIENT_ID = os.getenv('CLIENT_ID')
ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')

CLIP_COOLDOWN_SECONDS = int(os.getenv('CLIP_COOLDOWN_SECONDS', '30'))
RECONNECT_DELAY_SECONDS = int(os.getenv('RECONNECT_DELAY_SECONDS', '5'))
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

class TwitchBot:
    def __init__(self):
        self.sock: Optional[socket.socket] = None
        self.last_clip_time = 0
        self.cooldown = CLIP_COOLDOWN_SECONDS
        self.channel = CHANNEL.lower()
        self.connected = False

    def _connect_irc(self):
        try:
            self.sock = socket.socket()
            self.sock.connect((HOST, PORT))
            self.sock.send(f"PASS {TOKEN}\r\n".encode('utf-8'))
            self.sock.send(f"NICK {NICK}\r\n".encode('utf-8'))
            self.sock.send(f"JOIN {CHANNEL}\r\n".encode('utf-8'))
            self.connected = True
            logging.info(f"Conectado a {CHANNEL}")
            return True
        except socket.error as e:
            logging.error(f"Error al conectar al IRC: {e}")
            self.connected = False
            return False

    def connect(self):
        while not self.connected:
            if not self._connect_irc():
                logging.info(f"Reintentando conexión en {RECONNECT_DELAY_SECONDS} segundos...")
                time.sleep(RECONNECT_DELAY_SECONDS)

    def listen(self):
        while True:
            if not self.connected:
                self.connect()

            try:
                resp = self.sock.recv(2048).decode('utf-8')

                if resp.startswith('PING'):
                    self.sock.send("PONG :tmi.twitch.tv\r\n".encode('utf-8'))
                elif 'PRIVMSG' in resp:
                    user_info, message_content = resp.split('PRIVMSG', 1)[1].split(':', 1)
                    user = resp.split('!', 1)[0][1:].strip()
                    message = message_content.strip()

                    if message.lower().startswith('!clip'):
                        self._handle_clip_command(user, message) # Pasamos el mensaje completo

            except socket.error as e:
                logging.error(f"Error de socket, la conexión puede haberse perdido: {e}")
                self.connected = False
                self.sock.close()
            except Exception as e:
                logging.error(f"Error inesperado en el bucle de escucha: {e}")

    def _handle_clip_command(self, user: str, full_message: str):
        current_time = time.time()
        time_since_last_clip = current_time - self.last_clip_time

        if time_since_last_clip >= self.cooldown:
            # Extraer el título del mensaje para Discord
            command_prefix = "!clip"
            if len(full_message) > len(command_prefix) and full_message.lower().startswith(command_prefix):
                custom_embed_title = full_message[len(command_prefix):].strip()
            else:
                custom_embed_title = "" # Sin título personalizado

            logging.info(f"Comando !clip recibido de {user}. Título solicitado para Discord: '{custom_embed_title}'. Iniciando creación de clip...")
            threading.Thread(target=self._create_clip_and_respond, args=(user, custom_embed_title)).start()
        else:
            remaining_time = int(self.cooldown - time_since_last_clip)
            cooldown_message = f"@{user}, el comando !clip está en enfriamiento. Por favor, espera {remaining_time} segundos."
            self.send_message(cooldown_message)
            logging.info(cooldown_message)

    def _create_clip_and_respond(self, user: str, custom_embed_title: str):
        clip_data = self._create_clip()
        if clip_data:
            clip_id = clip_data.get('id')
            clip_url = clip_data.get('url')
            broadcaster_name = clip_data.get('broadcaster_name', CHANNEL.replace('#', '')) # Obtener el nombre del broadcaster
            current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logging.info(f"Clip creado: ID={clip_id}, URL={clip_url}, Broadcaster={broadcaster_name}, Usuario={user}")
            user = user.replace('#', '') 
            final_embed_title = custom_embed_title if custom_embed_title else f"Nuevo clip del canal {broadcaster_name}"
            self.send_message(f"@{user}, ¡clip creado! [{final_embed_title}] {clip_url}")

            # Obtener el avatar del usuario que envió el comando
            user_avatar = self._get_user_avatar(user)

            self._send_discord_clip_notification(
                user=user,
                clip_url=clip_url,
                clip_id=clip_id,
                timestamp=current_datetime,
                embed_title=final_embed_title,
                broadcaster_name=broadcaster_name,
                user_avatar=user_avatar
            )
            self.last_clip_time = time.time()
        else:
            self.send_message(f"@{user}, no se pudo crear el clip. Revisa los logs para más detalles.")

    def _create_clip(self) -> Optional[dict]:
        headers = {
            'Client-ID': CLIENT_ID,
            'Authorization': f'Bearer {ACCESS_TOKEN}',
        }
        try:
            # Obtener información del canal donde se ejecuta el bot (no del bot mismo)
            channel_name = os.getenv('CHANNEL_NAME')
            user_info_res = requests.get(f'https://api.twitch.tv/helix/users?login={channel_name}', headers=headers, timeout=5)
            user_info_res.raise_for_status()
            user_data = user_info_res.json().get('data')

            if not user_data:
                logging.error(f"La información del canal '{channel_name}' no está presente en la respuesta de la API. Respuesta: {user_info_res.json()}")
                return None

            broadcaster_id = user_data[0]['id']
            broadcaster_name = user_data[0]['display_name']
            logging.info(f"ID del Broadcaster: {broadcaster_id}, Nombre: {broadcaster_name}")

            clip_res = requests.post(f'https://api.twitch.tv/helix/clips?broadcaster_id={broadcaster_id}', headers=headers, timeout=5)
            clip_res.raise_for_status()

            clip_data = clip_res.json().get('data')

            if clip_data and clip_data[0] and 'id' in clip_data[0]:
                clip_id = clip_data[0]['id']
                clip_url = f"https://clips.twitch.tv/{clip_id}"
                logging.info(f"Clip creado con éxito. ID: {clip_id}, URL: {clip_url}")
                return {'id': clip_id, 'url': clip_url, 'broadcaster_name': broadcaster_name}
            else:
                logging.error(f"El ID del clip no se encontró en la respuesta de la API. Respuesta: {clip_res.json()}")
                return None

        except requests.exceptions.Timeout:
            logging.error("La solicitud a la API de Twitch excedió el tiempo de espera.")
            return None
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            error_message = e.response.text
            logging.error(f"Error HTTP durante la creación del clip: {status_code} - {error_message}")
            if status_code == 401:
                logging.error("Token de acceso o Client-ID inválido/expirado. ¡Asegúrate de que sean correctos!")
            elif status_code == 400 and "broadcaster is not live" in error_message.lower():
                logging.error("No se pudo crear el clip: El canal no está en vivo.")
            return None
        except requests.RequestException as e:
            logging.error(f"Error de solicitud general al interactuar con la API de Twitch: {e}")
            return None
        except Exception as e:
            logging.error(f"Error inesperado al crear el clip: {e}")
            return None

    def _send_discord_clip_notification(self, user: str, clip_url: str, clip_id: str, timestamp: str, embed_title: str, broadcaster_name: str, user_avatar: str):
        edit_url = f"https://dashboard.twitch.tv/content/video/clips?filters[query]={clip_id}&sort=created"

        embed = {
            "title": f"🎬 {embed_title}",  # Icono de cámara para el título
            "description": f"📹 ¡Un clip acaba de ser creado en el canal **{broadcaster_name}**!\n\n🎯 **ID del Clip:** `{clip_id}`",
            "color": 0x9146FF,
            "fields": [
                {
                    "name": "👤 Creador del clip",
                    "value": f"**{user}**",
                    "inline": True
                },
                {
                    "name": "🕒 Fecha y Hora",
                    "value": f"```{timestamp}```",
                    "inline": True
                },
                {
                    "name": "🎮 Canal",
                    "value": f"**{broadcaster_name}**",
                    "inline": True
                },
                {
                    "name": "▶️ Ver Clip",
                    "value": f"[🔗 Reproducir en Twitch]({clip_url})",
                    "inline": False
                },
                {
                    "name": "✏️ Editar Clip",
                    "value": f"({clip_url}/edit)",
                    "inline": False
                }
            ],
            "thumbnail": {
                "url": user_avatar  # Avatar del usuario que envió el comando
            },
            "footer": {
                "text": "🧡 PukeClips",
                "icon_url": "https://www.twitch.tv/favicon.ico"
            },
        }

        payload = {
            "embeds": [embed]
        }

        try:
            response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            response.raise_for_status()
            logging.info(f"Notificación de clip enviada a Discord para {clip_id}")
        except requests.exceptions.Timeout:
            logging.error("La solicitud al webhook de Discord excedió el tiempo de espera.")
        except requests.exceptions.HTTPError as e:
            logging.error(f"Error HTTP al enviar notificación a Discord: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logging.error(f"Error inesperado al enviar notificación a Discord: {e}")

    def send_message(self, message: str):
        if self.connected and self.sock:
            try:
                self.sock.send(f"PRIVMSG {self.channel} :{message}\r\n".encode('utf-8'))
                logging.info(f"Mensaje enviado: {message}")
            except socket.error as e:
                logging.error(f"Error al enviar mensaje, la conexión puede haberse perdido: {e}")
                self.connected = False
            except Exception as e:
                logging.error(f"Error inesperado al enviar mensaje: {e}")
        else:
            logging.warning(f"No conectado a IRC, no se pudo enviar el mensaje: {message}")

    def _get_user_avatar(self, username: str) -> str:
        """Obtiene el avatar del usuario de Twitch"""
        headers = {
            'Client-ID': CLIENT_ID,
            'Authorization': f'Bearer {ACCESS_TOKEN}',
        }
        try:
            user_res = requests.get(f'https://api.twitch.tv/helix/users?login={username}', headers=headers, timeout=5)
            user_res.raise_for_status()
            user_data = user_res.json().get('data')
            
            if user_data and len(user_data) > 0:
                avatar_url = user_data[0].get('profile_image_url', '')
                if avatar_url:
                    logging.info(f"Avatar obtenido para {username}: {avatar_url}")
                    return avatar_url
            
            logging.warning(f"No se pudo obtener el avatar para {username}")
            return "https://static-cdn.jtvnw.net/jtv_user_pictures/8a6381c7-d0c0-4576-b179-38bd5ce1d6af-profile_image-300x300.png"
            
        except Exception as e:
            logging.error(f"Error al obtener avatar del usuario {username}: {e}")
            # Retornar imagen por defecto de Twitch
            return "https://static-cdn.jtvnw.net/jtv_user_pictures/8a6381c7-d0c0-4576-b179-38bd5ce1d6af-profile_image-300x300.png"

if __name__ == '__main__':
    bot = TwitchBot()
    bot.connect()
    bot.listen()