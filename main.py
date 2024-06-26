import requests
import os, datetime, json, time, math, subprocess
import pytesseract
from display_progress import progress_for_pyrogram
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image

# config vars
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
LANG = os.environ.get("SUBTITLE_LANG") # Get this from https://en.m.wikipedia.org/wiki/List_of_ISO_639-2_codes
USE_CROP = os.environ.get("USE_CROP") # [Optional] Set to ANYTHING to enable crop mode

Bot = Client(
    "VidSubExtract-Bot",
    bot_token = BOT_TOKEN,
    api_id = API_ID,
    api_hash = API_HASH
)

START_TXT = """
Hi {}
I am Subtitle Extractor Bot.

> `I can extract hard-coded subtitle from videos.`

Send me a video to get started.
"""

START_BTN = InlineKeyboardMarkup(
        [[
        InlineKeyboardButton("Source Code", url="https://github.com/samadii/VidSubExtract-Bot"),
        ]]
    )

@Bot.on_message(filters.command(["start"]))
async def start(bot, update):
    text = START_TXT.format(update.from_user.mention)
    reply_markup = START_BTN
    await update.reply_text(
        text=text,
        disable_web_page_preview=True,
        reply_markup=reply_markup
    )

@Bot.on_message(filters.command(["cancel"]))
async def cancel_progress(_, m):
    try:
        os.remove("temp/vid.mp4")
    except:
        await m.reply("can't cancel. maybe there wasn't any progress in process.")
    else:
        await m.reply("canceled successfully.")
    await m.delete()
    os.remove("temp/srt.srt")

# Ensure the directory exists
dirs = "/app/vendor/tessdata"
if not os.path.exists(dirs):
    os.makedirs(dirs)

# Path to the language data file
path = os.path.join(dirs, f"{LANG}.traineddata")

# Download the language data file if it does not exist
if not os.path.exists(path):
    tessdata = f"https://github.com/tesseract-ocr/tessdata/raw/main/{LANG}.traineddata"
    data = requests.get(tessdata, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    if data.status_code == 200:
        with open(path, "wb") as f:
            f.write(data.content)
    else:
        print("Either the lang code is wrong or the lang is not supported.")

@Bot.on_message(filters.private & (filters.video | filters.document))
async def main(bot, m):
    if m.document and not m.document.mime_type.startswith("video/"):
        return
    media = m.video or m.document
    msg = await m.reply("`Downloading..`")
    c_time = time.time()
    file_dl_path = await bot.download_media(message=m, file_name="temp/vid.mp4", progress=progress_for_pyrogram, progress_args=("Downloading..", msg, c_time))
    await msg.edit_text("`Now Extracting..`")
    if m.video:
        duration = m.video.duration
    else:
        video_info = subprocess.check_output(f'ffprobe -v quiet -show_streams -select_streams v:0 -of json "{file_dl_path}"', shell=True).decode()
        fields = json.loads(video_info)['streams'][0]
        duration = int(fields['duration'].split(".")[0])
    sub_count = 0
    repeated_count = 0
    last_text = " "
    duplicate = True
    lastsub_time = 0
    time_to_finish = duration
    intervals = get_intervals(duration)
    # Extract frames every 100 milliseconds for ocr
    for interval in intervals:
        command = os.system(f'ffmpeg -ss {ms_to_time(interval)} -i "{file_dl_path}" -pix_fmt yuvj422p -vframes 1 -q:v 2 -y temp/output.jpg')
        if command != 0:
            await msg.delete()
            return

        try:
            if USE_CROP:
                img = Image.open("temp/output.jpg")
                width, height = img.size
                x1 = width // 7
                y1 = 3 * (height // 4)
                x2 = 6 * (width // 7)
                y2 = height
                crop_area = (x1, y1, x2, y2)
                cropped = img.crop(crop_area)
                cropped.save("temp/output.jpg")
            text = pytesseract.image_to_string("temp/output.jpg", LANG)
        except Exception as e:
            print(e)
            text = None
            pass

        if text != None and text[:1].isspace() == False :
            commons = list(set(text.split()) & set(last_text.split()))
            if len(commons) >= len(text.split()) / 2:
                duplicate = True
                repeated_count += 1
            else:
                duplicate = False

            if duplicate == False:
                lastsub_time = interval

            if repeated_count != 0 and duplicate == False:
                sub_count += 1
                from_time = ms_to_time(interval-100-(repeated_count*100))
                to_time = ms_to_time(interval)
                f = open("temp/srt.srt", "a+", encoding="utf-8")
                f.write(str(sub_count) + "\n" + from_time + " --> " + to_time + "\n" + last_text + "\n\n")
                duplicate = True
                repeated_count = 0
            last_text = text

        if interval/1000 == duration:
            ftime = ms_to_time(lastsub_time)
            ttime = ms_to_time(lastsub_time+10000)
            f = open("temp/srt.srt", "a+", encoding="utf-8")
            f.write(str(sub_count+1) + "\n" + ftime + " --> " + ttime + "\n" + last_text + "\n\n")

        if time_to_finish > 0:
            time_to_finish -= 0.1
            percentage = (duration - time_to_finish) * 100 / duration
            progress = "`Processing...`\n[{0}{1}]\nPercentage : {2}%\n\n".format(
                ''.join(["●" for i in range(math.floor(percentage / 5))]),
                ''.join(["○" for i in range(20 - math.floor(percentage / 5))]),
                round(percentage, 2)
            )
            try:
                await msg.edit_text(progress + "`For cancel progress, send` /cancel")
            except:
                pass

    f.close
    try:
        await bot.send_document(chat_id=m.chat.id, document="temp/srt.srt" , file_name=media.file_name.rsplit('.', 1)[0]+".srt")
    except ValueError:
        await msg.edit_text("Not any text detected.")
    else:
        await msg.delete()
    os.remove(file_dl_path)
    os.remove("temp/srt.srt")

def get_intervals(duration):
    intervals = []
    for i in range(0, duration+1):
        for x in range(0, 10):
            interval = (i+(x/10))*1000
            intervals.append(interval)
    return intervals

def ms_to_time(interval):
    ms2time = "0" + str(datetime.timedelta(milliseconds=interval))[:11]
    ms2time = f"{ms2time}.000" if not "." in ms2time else ms2time
    return ms2time

Bot.run()
