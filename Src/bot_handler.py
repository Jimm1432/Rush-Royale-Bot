import os
import time
import numpy as np
import logging
from subprocess import Popen, DEVNULL
# Image processing
import cv2
# internal
import port_scan
import bot_core
import bot_perception

import zipfile
import functools
import pathlib
import shutil
import requests
from tqdm.auto import tqdm


# from here https://stackoverflow.com/a/63831344
def download(url, filename):
    r = requests.get(url, stream=True, allow_redirects=True)
    if r.status_code != 200:
        r.raise_for_status()  # Will only raise for 4xx codes, so...
        raise RuntimeError(f"Request to {url} returned status code {r.status_code}")
    file_size = int(r.headers.get('Content-Length', 0))

    path = pathlib.Path(filename).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    desc = "(Unknown total file size)" if file_size == 0 else ""
    r.raw.read = functools.partial(r.raw.read, decode_content=True)  # Decompress if needed
    with tqdm.wrapattr(r.raw, "read", total=file_size, desc=desc) as r_raw:
        with path.open("wb") as f:
            shutil.copyfileobj(r_raw, f)

    return path


# Moves selected units from collection folder to deck folder for unit recognition options
def select_units(units):
    if os.path.isdir('units'):
        [os.remove('units/' + unit) for unit in os.listdir("units")]
    else:
        os.mkdir('units')
    # Read and write all images
    for new_unit in units:
        try:
            cv2.imwrite('units/' + new_unit, cv2.imread('all_units/' + new_unit))
        except Exception as e:
            print(e)
            print(f'{new_unit} not found')
            continue
    # Verify enough units were selected
    return len(os.listdir("units")) > 4


def start_bot_class(logger):
    # auto-install scrcpy if needed
    if not check_scrcpy(logger):
        return None
    bot = bot_core.Bot()
    return bot

# Loop for combat actions
def combat_loop(bot, combat, grid_df, mana_targets, user_target='demon_hunter.png'):  
    time.sleep(0.2)

    if combat <= 1:
        spawn_units(bot, num_units=4)
    else:
        # Upgrade units
        bot.mana_level(mana_targets, combat, hero_power=True)
        # Spawn unit
        spawn_units(bot, num_units=1)

    # Try to merge units
    grid_df, unit_series, merge_series, df_groups, info = bot.try_merge(prev_grid=grid_df, merge_target=user_target)
    return grid_df, unit_series, merge_series, df_groups, info

def spawn_units(bot, num_units=4):
    for _ in range(num_units):
        bot.click(450, 1360)

# Run the bot
def bot_loop(bot, info_event):
    # Load user config
    config = bot.config['bot']
    user_pve = config.getboolean('pve', True)
    user_ads = config.getboolean('watch_ad', True)
    user_treasure_map_green = config.getboolean('treasure_map_green', True)
    user_treasure_map_gold = config.getboolean('treasure_map_gold', False)
    user_shaman = config.getboolean('require_shaman', False)
    user_clan_collect = config.getboolean('clan_collect', True)
    user_clan_tournament = config.getboolean('clan_tournament', True)
    user_clan_request_epic = config['request_epic'] + '.png' if config['request_epic'] else ''
    user_clan_request_common_rare = config['request_common_rare'] + '.png' if config['request_common_rare'] else ''
    user_floor = int(config.get('floor', 10))
    user_level = np.fromstring(config['mana_level'], dtype=int, sep=',')
    user_target = config['dps_unit'].split('.')[0] + '.png'
    shop_target = np.fromstring(config['shop_item'], dtype=int, sep=',')
    bot.logger.info(f'PVE = {user_pve}')
    bot.logger.info(f'ADs = {user_ads}')
    bot.logger.info(f'Green maps = {user_treasure_map_green}')
    bot.logger.info(f'Gold maps = {user_treasure_map_gold}')
    bot.logger.info(f'Req Shaman for PvE = {user_shaman}')
    bot.logger.info(f'Collect clan chat = {user_clan_collect}')
    bot.logger.info(f'Play clan tourney = {user_clan_tournament}')
    # Load optional settings
    require_shaman = user_shaman
    max_loops = int(config.get('max_loops', 800))  # this will increase time waiting when logging in from mobile
    # Dev options (only adds images to dataset, rank ai can be trained with bot_perception.quick_train_model)
    train_ai = False
    # State variables
    wait = 0
    combat = 0
    watch_ad = False
    clan_collect = False
    clan_request = False
    grid_df = None
    # Wait for login
    time.sleep(5)
    # Main loop
    bot.logger.debug(f'Bot mainloop started')
    # Wait for game to load
    while (not bot.bot_stop):
        # Pass shop_targets
        bot.shop_item = shop_target
        bot.store_visited = False # Reset the store_visited attribute at the beginning of each loop iteration
        # Fetch screen and check state
        output = bot.battle_screen(start=False)
        if output[1] == 'fighting':
            watch_ad = user_ads
            clan_collect = user_clan_collect
            clan_request = True if user_clan_request_epic or user_clan_request_common_rare else False
            wait = 0
            combat += 1
            if combat > max_loops:
                bot.restart_RR()
                combat = 0
                continue
            elif bot.bot_stop:
                return
            elif require_shaman and not (output[0] == 'shaman_opponent.png').any(axis=None):
                bot.logger.info('Shaman not found, checking again...')
                if any([(bot.battle_screen(start=False)[0] == 'shaman_opponent.png').any(axis=None) for i in range(1)]):
                    continue
                bot.logger.warning('Leaving game')
                bot.restart_RR(quick_disconnect=True)
            # Combat Section
            grid_df, bot.unit_series, bot.merge_series, bot.df_groups, bot.info = combat_loop(bot, combat, grid_df, user_level, user_target)
            bot.grid_df = grid_df.copy()
            bot.combat = combat
            bot.output = output[1]
            bot.combat_step = 1
            info_event.set()
            # Wait until late stage in combat then if consistency is ok and not stagnate save all units for ML model
            if combat == 25 and 5 < grid_df['Age'].mean() < 50 and train_ai:
                bot_perception.add_grid_to_dataset()
        elif (output[1] == 'home'):
            if watch_ad:
                [bot.watch_ads() for i in range(3)]
                watch_ad = False
            if clan_collect:
                bot.collect_clan_chat()
                clan_collect = False
            if clan_request:
                bot.request_clan_chat(user_clan_request_epic, user_clan_request_common_rare)
                clan_request = False
            if (watch_ad == False) and (clan_collect == False) and (clan_request == False):
                output = bot.battle_screen(start=True, pve=user_pve, clan_tournament=user_clan_tournament, floor=user_floor)
        else:
            combat = 0
            bot.logger.info(f'{output[1]}, wait count: {wait}')
            output = bot.battle_screen(start=False, pve=user_pve, clan_tournament=user_clan_tournament, floor=user_floor)
            wait += 1
            if wait > 15:
                bot.logger.warning('RESTARTING')
                bot.restart_RR(),
                wait = 0


def check_scrcpy(logger):
    if os.path.exists('.scrcpy/scrcpy.exe'):
        return True
    else:
        logger.info('scrcpy is not installed')
        # Download
        download('https://github.com/Genymobile/scrcpy/releases/download/v1.25/scrcpy-win64-v1.25.zip', 'scrcpy.zip')
        with zipfile.ZipFile('scrcpy.zip', 'r') as zip_ref:
            for member in zip_ref.namelist():
                if not member.endswith('/'):  # Exclude directories
                    # Extract the file directly into the .scrcpy folder
                    extracted_path = os.path.join('.scrcpy', os.path.basename(member))
                    os.makedirs(os.path.dirname(extracted_path), exist_ok=True)  # Create the directory if it doesn't exist
                    with zip_ref.open(member) as source, open(extracted_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
        # Verify
        if os.path.exists('.scrcpy/scrcpy.exe'):
            logger.info('scrcpy successfully installed')
            # Remove the zip file
            os.remove('scrcpy.zip')
            return True