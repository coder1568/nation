import os
import shutil
import asyncio
import time
import random
import json
from telethon import TelegramClient, events
from PIL import Image, ImageChops

# == Configuration ==
api_id = 28401351
api_hash = 'dc456fc9e51b67fb43e1c5a900aa7baa'
group_ids = [
    -4704635060,
    -1002674143030,
    -1002621319023,
    -1002256028252,
    -1002533001004,
    -4760358699,
    -4692623266,
]

client = TelegramClient('session', api_id, api_hash)

# == Ensure folders ==
os.makedirs("known_images", exist_ok=True)
os.makedirs("unknown_images", exist_ok=True)
os.makedirs("temp", exist_ok=True)

# == Persistent Points ==
POINTS_FILE = "points.json"
if os.path.exists(POINTS_FILE):
    with open(POINTS_FILE, "r") as f:
        points_data = json.load(f)
else:
    points_data = {str(gid): 0 for gid in group_ids}

def save_points():
    with open(POINTS_FILE, "w") as f:
        json.dump(points_data, f, indent=2)

# == Hashing functions ==
def average_hash(img_path, hash_size=8):
    try:
        img = Image.open(img_path).convert("L").resize((hash_size, hash_size))
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        return ''.join(['1' if p > avg else '0' for p in pixels])
    except:
        return None

def hamming_distance(h1, h2):
    return sum(c1 != c2 for c1, c2 in zip(h1, h2))

def is_similar_hash(h1, h2, threshold=3):
    if h1 is None or h2 is None:
        return False
    return hamming_distance(h1, h2) <= threshold

def double_check(img1_path, img2_path):
    try:
        img1 = Image.open(img1_path).resize((128, 128)).convert("L")
        img2 = Image.open(img2_path).resize((128, 128)).convert("L")
        diff = ImageChops.difference(img1, img2)
        return diff.getbbox() is None
    except:
        return False

# == Load known hashes ==
known_hashes = {}
for fname in os.listdir("known_images"):
    path = os.path.join("known_images", fname)
    if os.path.isfile(path):
        h = average_hash(path)
        if h:
            known_hashes[fname] = h

# == Group state ==
group_states = {
    gid: {"last_sent": 0, "last_seen": 0, "active": True} for gid in group_ids
}
GROUP_COUNT = len(group_ids)

# == Flood control delay ==
min_delay = 2.5
max_delay = 4.5
current_delay = 3.5
max_delay_limit = 60
min_delay_limit = 2.0
delay_step = 5

# == Scheduler ==
async def group_scheduler():
    global current_delay
    await client.start()
    while True:
        start_time = time.time()

        for gid in group_ids:
            now = time.time()
            if not group_states[gid]["active"]:
                if now - group_states[gid]["last_seen"] < 900:
                    continue  # skip inactive group until 15 mins passed

            try:
                await client.send_message(gid, "/nation")
                group_states[gid]["last_sent"] = now
                print(f"[{gid}] /nation sent at {now:.2f}")

                if current_delay > min_delay_limit:
                    current_delay = max(min_delay_limit, current_delay - delay_step)
                    print(f"Decreasing delay to {current_delay:.1f} sec")

            except Exception as e:
                err = str(e)
                print(f"[{gid}] Send failed: {err}")
                if "A wait of" in err:
                    try:
                        wait_sec = int(err.split("A wait of ")[1].split(" seconds")[0])
                    except:
                        wait_sec = 30
                    print(f"[{gid}] Flood wait: {wait_sec} sec")
                    current_delay = min(max_delay_limit, current_delay + wait_sec)
                    print(f"Increasing delay to {current_delay:.1f} sec")
                    await asyncio.sleep(wait_sec)
                    continue
                else:
                    await asyncio.sleep(10)
                    continue

            delay_time = random.uniform(max(min_delay, current_delay - 1), min(max_delay, current_delay + 1))
            print(f"Sleeping for {delay_time:.2f} sec before next group")
            await asyncio.sleep(delay_time)

        elapsed = time.time() - start_time
        if elapsed < GROUP_COUNT * min_delay:
            await asyncio.sleep(GROUP_COUNT * min_delay - elapsed)

# == Message handler ==
@client.on(events.NewMessage)
async def message_handler(event):
    gid = event.chat_id
    if gid not in group_ids or not event.photo:
        return
    asyncio.create_task(process_image(event))

async def process_image(event):
    gid = event.chat_id
    group_states[gid]["last_seen"] = time.time()
    group_states[gid]["active"] = True

    t0 = time.time()
    filename = f"temp/{gid}_{event.id}.jpg"
    file = await event.download_media(file=filename)
    print(f"[{gid}] Image received at {t0:.2f}, saved to {file}")

    img_hash = average_hash(file)
    matched = False

    for fname, khash in known_hashes.items():
        if is_similar_hash(img_hash, khash, threshold=3):
            known_path = os.path.join("known_images", fname)
            if double_check(file, known_path):
                country = os.path.splitext(fname)[0]
                await event.reply(country)
                print(f"[{gid}] Matched: {country}, replied at {time.time():.2f}")
                matched = True
                points_data[str(gid)] += 10_000
                print(f"[{gid}] Total Points: {points_data[str(gid)]}")
                save_points()
                break

    if not matched:
        dest_folder = f"unknown_images/{gid}"
        os.makedirs(dest_folder, exist_ok=True)
        dest = os.path.join(dest_folder, os.path.basename(file))
        shutil.move(file, dest)
        print(f"[{gid}] Unknown saved: {dest}")
    else:
        os.remove(file)

# == Run ==
with client:
    client.loop.create_task(group_scheduler())
    client.run_until_disconnected()