import asyncio
import io
import logging
import os
import re
import tempfile
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

TOKEN = (os.getenv("BOT_TOKEN") or os.getenv("DISCORD_BOT_TOKEN") or "").strip()
MAX_INPUT_BYTES = int(os.getenv("MAX_INPUT_BYTES", str(8 * 1024 * 1024)))
MAX_OUTPUT_BYTES = int(os.getenv("MAX_OUTPUT_BYTES", str(25 * 1024 * 1024)))
ENGINE_FILE = Path(__file__).with_name("WSFuscate.html")
ALLOWED_EXTENSIONS = {".lua", ".luau", ".txt"}
BUILD_TIMEOUT_MS = int(os.getenv("BUILD_TIMEOUT_MS", "180000"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("wsfuscate-bot")

intents = discord.Intents.none()
bot = commands.Bot(command_prefix="!", intents=intents)
build_semaphore = asyncio.Semaphore(2)


async def obfuscate_with_engine(source_text: str) -> str:
    """Run the uploaded WSFuscate browser engine in an isolated headless Chromium page."""
    if not ENGINE_FILE.is_file():
        raise RuntimeError("WSFuscate.html 파일이 봇과 같은 폴더에 없습니다.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                accept_downloads=False,
                java_script_enabled=True,
                service_workers="block",
            )
            page = await context.new_page()
            page.set_default_timeout(BUILD_TIMEOUT_MS)
            await page.goto(ENGINE_FILE.resolve().as_uri(), wait_until="load")

            # The source is assigned only to this isolated page; it is never posted to Discord.
            await page.locator("#src").evaluate(
                "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', {bubbles:true})); }",
                source_text,
            )

            # Explicitly keep the engine's standard strongest defaults:
            # level 5, VM on, Balanced ISA, with the bundled default transformations.
            await page.locator("#level").evaluate("(el) => { el.value = '5'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
            await page.locator("#o_vm").evaluate("(el) => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles:true})); }")
            await page.locator("#vm_profile").select_option("balanced")

            await page.locator("#run").click()

            try:
                await page.wait_for_function(
                    """() => {
                        const s = document.querySelector('#status');
                        const o = document.querySelector('#out');
                        return !!s && !!o && (
                          s.textContent.startsWith('Done:') ||
                          s.textContent.startsWith('Error:') ||
                          s.textContent.startsWith('Build blocked:') ||
                          s.textContent.startsWith('Inline macro syntax error:') ||
                          s.textContent.startsWith('Source is empty.')
                        );
                    }""",
                    timeout=BUILD_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                raise RuntimeError("난독화 처리 시간이 초과되었습니다.")

            status = (await page.locator("#status").inner_text()).strip()
            output = await page.locator("#out").input_value()

            if not status.startswith("Done:"):
                # Do not include source text or engine internals in the public error.
                safe_status = status[:500] if status else "엔진이 완료 상태를 반환하지 않았습니다."
                raise RuntimeError(f"난독화 실패: {safe_status}")

            if not output.strip():
                raise RuntimeError("난독화 결과가 비어 있습니다.")
            if len(output.encode("utf-8")) > MAX_OUTPUT_BYTES:
                raise RuntimeError("난독화 결과가 설정된 최대 출력 크기를 초과했습니다.")
            return output
        finally:
            await browser.close()


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        log.info("Logged in as %s; synced %d slash commands.", bot.user, len(synced))
    except Exception:
        log.exception("Slash command sync failed")


@bot.tree.command(name="obf", description="Lua/Luau 파일을 WSFuscate로 난독화합니다.")
@app_commands.describe(file="난독화할 .lua, .luau 또는 .txt 파일")
async def obf(interaction: discord.Interaction, file: discord.Attachment):
    # Respond ephemerally before downloading/processing anything.
    await interaction.response.defer(ephemeral=True, thinking=True)

    filename = Path(file.filename or "source.lua").name
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        await interaction.followup.send(
            "지원하지 않는 파일 형식입니다. `.lua`, `.luau`, `.txt` 파일을 선택해 주세요.",
            ephemeral=True,
        )
        return

    if file.size <= 0 or file.size > MAX_INPUT_BYTES:
        await interaction.followup.send(
            f"파일 크기는 1바이트 이상 {MAX_INPUT_BYTES // (1024 * 1024)}MiB 이하여야 합니다.",
            ephemeral=True,
        )
        return

    try:
        raw = await file.read(use_cached=True)
        if not raw or len(raw) > MAX_INPUT_BYTES:
            raise ValueError("파일이 비어 있거나 허용 크기를 초과했습니다.")

        # Strict UTF-8 decoding avoids silently corrupting source text.
        source_text = raw.decode("utf-8-sig")
        del raw

        async with build_semaphore:
            result = await obfuscate_with_engine(source_text)

        result_bytes = result.encode("utf-8")
        result_file = discord.File(
            fp=io.BytesIO(result_bytes),
            filename="obfuscate.txt",
            description="WSFuscate obfuscation result",
        )

        # Only the invoking user can see this response. Nothing is sent to the channel.
        await interaction.followup.send(
            content="난독화가 완료되었습니다. 결과 파일을 비공개로 전달합니다.",
            file=result_file,
            ephemeral=True,
        )
        del source_text, result, result_bytes

    except UnicodeDecodeError:
        await interaction.followup.send(
            "UTF-8 텍스트 파일만 처리할 수 있습니다.",
            ephemeral=True,
        )
    except Exception as exc:
        log.warning("Obfuscation request failed (%s): %s", type(exc).__name__, str(exc)[:300])
        await interaction.followup.send(
            "난독화에 실패했습니다. 파일 형식과 코드 문법을 확인한 뒤 다시 시도해 주세요.",
            ephemeral=True,
        )


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("BOT_TOKEN 또는 DISCORD_BOT_TOKEN 환경 변수를 설정하세요.")
    if not ENGINE_FILE.is_file():
        raise SystemExit("WSFuscate.html 파일이 봇과 같은 폴더에 있어야 합니다.")
    bot.run(TOKEN)
