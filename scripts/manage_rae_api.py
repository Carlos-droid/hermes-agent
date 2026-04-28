import os
import smtplib
import imaplib
import email
import re
import sys
import time
from email.mime.text import MIMEText
from pathlib import Path
from dotenv import load_dotenv

# Cargar configuración desde .env
load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT = "marsanben92@gmail.com"

SOLICITUD_BODY = """Nombre del proyecto: Hermes Agent: Orchestrator for Smart-RAG Editorial Suite

Descripción:
Hermes es un orquestador agéntico avanzado que coordina el ecosistema "Smart-RAG", una suite editorial para la generación de contenido técnico, histórico y naval de larga extensión (+2500 palabras). Utilizaremos la API de la RAE para realizar validaciones léxicas y correcciones académicas automáticas "en caliente" durante la fase de redacción y corrección de estilo.

Tipo de proyecto:
- Educativo / Académico
- Open Source

URL del proyecto:
https://github.com/NousResearch/hermes-agent

Requests estimadas por día:
- 1,000 - 5,000 (tier Developer)

Email de contacto:
pedernal001@gmail.com

Términos de uso:
- Entiendo que esta API es no oficial y no está afiliada con la RAE
- Entiendo que la API key puede ser revocada en caso de abuso
- No usaré la API para spam o scraping masivo para redistribución"""

def phase1_send():
    print(f">>> FASE 1: Enviando solicitud desde {GMAIL_USER} a {RECIPIENT}...")
    try:
        msg = MIMEText(SOLICITUD_BODY)
        msg['Subject'] = "Solicitud de API Key - Tier Developer - Proyecto Hermes & Smart-RAG"
        msg['From'] = GMAIL_USER
        msg['To'] = RECIPIENT

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.send_message(msg)
        print("✅ Email enviado con éxito.")
    except Exception as e:
        print(f"❌ Error al enviar email: {e}")

def phase2_monitor():
    print(">>> FASE 2: Buscando respuesta de la RAE en el Inbox...")
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(GMAIL_USER, GMAIL_PASSWORD)
        mail.select('inbox')

        # Buscar emails de la dirección específica
        status, data = mail.search(None, f'(FROM "{RECIPIENT}")')
        ids = data[0].split()
        
        if not ids:
            print("⏳ Aún no hay respuesta. Vigilancia activa.")
            return False

        # Leer el último
        latest_id = ids[-1]
        status, data = mail.fetch(latest_id, '(RFC822)')
        raw_email = data[0][1]
        msg = email.message_from_bytes(raw_email)
        
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode()
                    break
        else:
            body = msg.get_payload(decode=True).decode()

        # Buscar la API Key
        match = re.search(r"API[ _]KEY[:\s]+([a-zA-Z0-9_\-]+)", body, re.IGNORECASE)
        if match:
            api_key = match.group(1)
            print(f"🎯 ¡API KEY ENCONTRADA! -> {api_key[:4]}****")
            phase3_integrate(api_key)
            return True
        else:
            print("📬 Respuesta recibida pero sin clave detectable.")
            return False

    except Exception as e:
        print(f"❌ Error en monitoreo IMAP: {e}")
        return False

def phase3_integrate(key):
    print(">>> FASE 3: Integrando API Key...")
    env_path = Path(".env")
    if env_path.exists():
        content = env_path.read_text()
        if "RAE_API_KEY=" in content:
            content = re.sub(r"RAE_API_KEY=.*", f"RAE_API_KEY={key}", content)
        else:
            content += f"\nRAE_API_KEY={key}\n"
        env_path.write_text(content)
        print("✅ Configuración actualizada.")

if __name__ == "__main__":
    if "--monitor" in sys.argv:
        phase2_monitor()
    else:
        phase1_send()
