"""
🎌 Crunchyroll Notifier Bot para Telegram
==========================================
Notifica nuevos episodios con formato exacto.
"""

import asyncio
import json
import logging
import os
import time

impo    with open(CR_TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log.info("✅ Token guardado.")


async def get_cr_token_from_cookie(etp_rt: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            CR_AUTH_URL,
            data={
                "grant_type":  "etp_rt_cookie",
                "scope":       "offline_access",
                "device_type": "Chrome on Windows",
                "device_id":   "crunchyroll-notifier-bot",
            },
            auth=(CR_CLIENT_ID, CR_CLIENT_SECRET),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie":       f"etp_rt={etp_rt}",
            },
            timeout=15,
        )
        resp.raise_for_status()
        token_data = resp.json()
        token_data["etp_rt"] = etp_rt
        save_token(token_data)
        return token_data["access_token"]


async def refresh_cr_token(token_data: dict) -> str:
    if token_data.get("refresh_token"):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                CR_AUTH_URL,
                data={
                    "refresh_token": token_data["refresh_token"],
                    "grant_type":    "refresh_token",
                    "scope":         "offline_access",
                },
                auth=(CR_CLIENT_ID, CR_CLIENT_SECRET),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            if resp.status_code == 200:
                new_data = resp.json()
                new_data["etp_rt"] = token_data.get("etp_rt", "")
                save_token(new_data)
                log.info("🔄 Token renovado.")
                return new_data["access_token"]

    if token_data.get("etp_rt"):
        return await get_cr_token_from_cookie(token_data["etp_rt"])

    raise RuntimeError("❌ No se pudo renovar el token. Usa /login de nuevo.")


async def ensure_token() -> str:
    token_data = load_token()
    if token_data:
        return token_data["access_token"]
    if os.path.exists(CR_TOKEN_FILE):
        with open(CR_TOKEN_FILE) as f:
            old_data = json.load(f)
        return await refresh_cr_token(old_data)
    raise RuntimeError("❌ No hay token válido. Usa /login.")


# ─────────────────────────────────────────────────────────────────────────────
#  CRUNCHYROLL API — obtener episodios con datos completos
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_episodes(n: int = 50) -> list[dict]:
    """
    Usa el endpoint de browse con locale es-419 para obtener
    los episodios más recientes. Loguea el primer item para debug.
    """
    access_token = await ensure_token()
    headers = {
        "Authorization":  f"Bearer {access_token}",
        "Accept-Language": LOCALE,
    }

    # Pedimos con locale ES-419 para que venga doblado al español si existe,
    # y también pedimos sin preferred_audio para capturar todos los idiomas
    params = {
        "locale":  LOCALE,
        "n":       str(n),
        "sort_by": "newly_added",
        "type":    "episode",
        "ratings": "true",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(CR_BROWSE_URL, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()

    items = data.get("items", [])

    # Debug: mostrar las claves del primer episodio para entender la estructura
    if items:
        log.info(f"🔍 Claves del ep: {list(items[0].keys())}")
        log.info(f"🔍 Primer ep: {json.dumps(items[0], ensure_ascii=False, indent=2)[:800]}")

    return items


# ─────────────────────────────────────────────────────────────────────────────
#  EXTRAER DATOS CORRECTAMENTE según la estructura real de la API
# ─────────────────────────────────────────────────────────────────────────────

def extract_ep_data(ep: dict) -> dict:
    """
    La API de CR puede devolver los datos en distintos niveles.
    Esta función normaliza todo a un dict plano con los campos que necesitamos.
    """
    # A veces el episodio está dentro de ep["episode_metadata"] o ep["panel"]
    meta = ep.get("episode_metadata") or ep.get("panel", {}) or ep

    # Nombre del anime (series)
    series = (
        ep.get("series_title")
        or meta.get("series_title")
        or ep.get("title", "").split(" - ")[0]
        or "—"
    )

    # Título del episodio
    title = (
        ep.get("title")
        or meta.get("title")
        or "Sin título"
    )
    # Quitar el nombre de la serie del título si viene repetido
    if series and title.startswith(series + " - "):
        title = title[len(series) + 3:]

    # Número de episodio
    ep_number = (
        ep.get("episode_number")
        or meta.get("episode_number")
        or ep.get("episode")
        or meta.get("episode")
        or "?"
    )

    # Descripción
    description = (
        ep.get("description")
        or meta.get("description")
        or ""
    ).strip()

    # IDs
    ep_id     = ep.get("id") or meta.get("id") or ""
    series_id = ep.get("series_id") or meta.get("series_id") or ""
    season_id = ep.get("season_id") or meta.get("season_id") or ""
    slug      = ep.get("slug_title") or meta.get("slug_title") or ep_id

    # Audio
    audio_locale = (
        ep.get("audio_locale")
        or meta.get("audio_locale")
        or "ja-JP"
    )

    # Subtítulos — pueden estar en varios lugares
    sub_locales = list(ep.get("subtitle_locales", []) or meta.get("subtitle_locales", []))

    # También pueden estar dentro de "versions"
    versions = ep.get("versions") or meta.get("versions") or []
    for ver in versions:
        for loc in ver.get("subtitle_locales", []):
            if loc not in sub_locales:
                sub_locales.append(loc)

    # Thumbnail
    thumbnail = None
    images = ep.get("images") or meta.get("images") or {}
    thumbs = images.get("thumbnail", [[]])
    if thumbs and thumbs[0]:
        thumbnail = thumbs[0][-1].get("source")

    return {
        "id":           ep_id,
        "series":       series,
        "title":        title,
        "ep_number":    ep_number,
        "description":  description,
        "series_id":    series_id,
        "season_id":    season_id,
        "slug":         slug,
        "audio_locale": audio_locale,
        "sub_locales":  sub_locales,
        "thumbnail":    thumbnail,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  PERSISTENCIA
# ─────────────────────────────────────────────────────────────────────────────

def load_seen() -> set[str]:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set[str]):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def is_first_run() -> bool:
    return not os.path.exists(SEEN_FILE)


# ─────────────────────────────────────────────────────────────────────────────
#  FORMATEO DEL MENSAJE
# ─────────────────────────────────────────────────────────────────────────────

def build_message(d: dict) -> tuple[str, str | None, InlineKeyboardMarkup]:
    cr_url = f"https://www.crunchyroll.com/watch/{d['id']}/{d['slug']}"

    # Los IDs ya vienen con prefijo GT/GS desde la API, no agregar doble
    raw_z  = d['series_id'] or ""
    raw_s  = d['season_id'] or ""
    raw_id = d['id']        or ""

    z_id   = raw_z  if raw_z  else "—"
    s_id   = raw_s  if raw_s  else "—"
    ext_id = f"EPI.{raw_id}" if raw_id else "—"

    audio_label = AUDIO_FLAGS.get(d["audio_locale"], f"🌐 {d['audio_locale']}")

    # Subtítulos como banderas
    flags_seen = []
    for loc in d["sub_locales"]:
        f = SUB_FLAGS.get(loc)
        if f and f not in flags_seen:
            flags_seen.append(f)
    sub_text = ", ".join(flags_seen) if flags_seen else "N/A"

    # Si es doblaje en español latino no mostramos línea de subtítulos
    is_es_latino = d["audio_locale"] == "es-419"
    sub_line = "" if is_es_latino else f"<b>Subtítulos:</b> {sub_text}\n"

    text = (
        f"<b>Anime:</b> 【{d['series']}】 | <b>Z:</b> <code>{z_id}</code> | <b>S:</b> <code>{s_id}</code>\n"
        f"<b>Título:</b> '{d['title']}'\n"
        f"<b>Episodio:</b> {d['ep_number']} | <b>ID:</b> <code>{raw_id}</code> | <b>Ext. ID:</b> <code>{ext_id}</code>\n"
        f"<b>Categoría:</b> Anime | <b>Enlace:</b> <a href='{cr_url}'>Crunchyroll</a>\n"
        f"<b>Idioma:</b> {audio_label}\n"
        f"{sub_line}"
        f"\n"
        f"<b>Sinopsis:</b> <i>{d['description'] or 'Sin sinopsis.'}</i>"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Ver en Crunchyroll", url=cr_url)]
    ])

    return text, d["thumbnail"], keyboard


# ─────────────────────────────────────────────────────────────────────────────
#  ENVÍO
# ─────────────────────────────────────────────────────────────────────────────

async def send_episode(bot: Bot, d: dict):
    text, thumbnail, keyboard = build_message(d)
    try:
        if thumbnail:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=thumbnail,
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        log.info(f"📨 Enviado: {d['series']} Ep.{d['ep_number']}")
    except Exception as e:
        log.error(f"❌ Error: {e}\nTexto: {text[:200]}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
#  LÓGICA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

async def check_and_notify(bot: Bot):
    first_run = is_first_run()
    seen = load_seen()

    try:
        raw_eps = await fetch_episodes(n=50)
    except Exception as e:
        log.error(f"Error al obtener episodios: {e}")
        return

    episodes = [extract_ep_data(ep) for ep in raw_eps]
    episodes = [ep for ep in episodes if ep["id"]]

    if first_run:
        to_send = episodes[:INITIAL_LIMIT]
        to_skip = episodes[INITIAL_LIMIT:]

        log.info(f"🚀 Primera ejecución — enviando {len(to_send)}, saltando {len(to_skip)}")

        # Marcar TODOS como vistos primero (incluidos los que se van a enviar)
        for ep in episodes:
            seen.add(ep["id"])

        # Guardar ANTES de enviar para que no se repitan si el bot se reinicia
        save_seen(seen)

            if len(context.args) != 1:
        await update.message.reply_text(
            "📋 <b>Cómo obtener tu cookie etp_rt:</b>\n\n"
            "1. Inicia sesión en crunchyroll.com\n"
            "2. F12 → <b>Application</b> → <b>Cookies</b> → crunchyroll.com\n"
            "3. Copia el valor de <code>etp_rt</code>\n\n"
            "Luego: <code>/login VALOR</code>",
            parse_mode="HTML",
        )
        return
    etp_rt = context.args[0]
    await update.message.reply_text("🔐 Autenticando...")
    try:
        await get_cr_token_from_cookie(etp_rt)
        await update.message.reply_text("✅ ¡Autenticado correctamente!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_check(update, context: ContextTypes.DEFAULT_TYPE):
