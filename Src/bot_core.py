import os
import time
import numpy as np
import pandas as pd
import logging
from subprocess import Popen, DEVNULL
# Android ADB
from scrcpy import Client, const
# Image processing
import cv2
# internal
import bot_perception
import port_scan

SLEEP_DELAY = 0.1


class Bot:

    def __init__(self, device=None):
        self.bot_stop = False
        self.combat = self.output = self.grid_df = self.unit_series = self.merge_series = self.df_groups = self.info = self.combat_step = None
        os.makedirs("units", exist_ok=True)
        self.selected_units = os.listdir("units")
        self.logger = logging.getLogger('__main__')
        if device is None:
            device = port_scan.get_device()
        if not device:
            raise Exception("No device found!")
        self.device = device
        self.bot_id = self.device.split(':')[-1]
        self.shell(f'.scrcpy\\adb connect {self.device}')
        # Try to launch application through ADB shell
        self.shell('monkey -p com.my.defense 1')
        # Check if 'bot_feed.png' exists
        if not os.path.isfile(f'bot_feed_{self.bot_id}.png'):
            self.getScreen()
        self.screenRGB = cv2.imread(f'bot_feed_{self.bot_id}.png')
        self.client = Client(device=self.device)
        # Start scrcpy client
        self.client.start(threaded=True)
        self.logger.info('Connecting to Bluestacks')
        time.sleep(0.5)
        # Turn off video stream (spammy)
        self.client.alive = False

    def __exit__(self, exc_type, exc_value, traceback):
        self.bot_stop = True
        self.logger.info('Exiting bot')
        self.client.stop()

    # Function to send ADB shell command
    def shell(self, cmd):
        p = Popen([".scrcpy\\adb", '-s', self.device, 'shell', cmd], stdout=DEVNULL, stderr=DEVNULL)
        p.wait()

    # Send ADB to click screen
    def click(self, x, y, delay_mult=1):
        self.client.control.touch(x, y, const.ACTION_DOWN)
        time.sleep(SLEEP_DELAY / 2 * delay_mult)
        self.client.control.touch(x, y, const.ACTION_UP)
        time.sleep(SLEEP_DELAY * delay_mult)

    # Click button coords offset and extra delay
    def click_button(self, pos):
        coords = np.array(pos) + 10
        self.click(*coords)
        time.sleep(SLEEP_DELAY * 10)

    # Swipe on combat grid to merge units
    def swipe(self, start, end, menu_scrolling=False):
        boxes, box_size = get_grid()
        # Offset from box edge 
        offset = -143 if menu_scrolling else 10 # (box[0,0] starts at [153,945]) with an offset of -143, the bot will scroll 10 pixels from the edge to avoid other elements
        self.client.control.swipe(*boxes[start[0], start[1]] + offset, *boxes[end[0], end[1]] + offset, 20, 1 / 60)

    # Send key command, see py-scrcpy consts
    def key_input(self, key):
        self.client.control.keycode(key)

    # Force restart the game through ADC, or spam 10 disconnects to abandon match
    def restart_RR(self, quick_disconnect=False):
        if quick_disconnect:
            for i in range(15):
                self.shell('monkey -p com.my.defense 1')  # disconnects really quick for unknown reasons
            return
        # Force kill game through ADB shell
        self.shell('am force-stop com.my.defense')
        time.sleep(2)
        # Launch application through ADB shell
        self.shell('monkey -p com.my.defense 1')
        time.sleep(10)  # wait for app to load

    # Take screenshot of device screen and load pixel values
    def getScreen(self):
        bot_id = self.device.split(':')[-1]
        p = Popen(['.scrcpy\\adb', 'exec-out', 'screencap', '-p', '>', f'bot_feed_{bot_id}.png'], shell=True)
        p.wait()
        # Store screenshot in class variable if valid
        new_img = cv2.imread(f'bot_feed_{bot_id}.png')
        if new_img is not None:
            self.screenRGB = new_img
        else:
            self.logger.warning('Failed to get screen')

    # Crop latest screenshot taken
    def crop_img(self, x, y, dx, dy, name='icon.png'):
        # Load screen
        img_rgb = self.screenRGB
        img_rgb = img_rgb[y:y + dy, x:x + dx]
        cv2.imwrite(name, img_rgb)

    def getMana(self):
        return int(self.getText(220, 1360, 90, 50, new=False, digits=True))

    # find icon on screen
    def getXYByImage(self, target, new=True):
        valid_targets = ['battle_icon', 'collect_pvp', 'pvp_button', 'back_button', '0watch_ad', '0gift.png', '1cont_button', 'fighting']
        if not target in valid_targets:
            return "INVALID TARGET"
        if new:
            self.getScreen()
        imgSrc = f'icons/{target}.png'
        img_rgb = self.screenRGB
        img_gray = cv2.cvtColor(img_rgb, cv2.COLOR_BGR2GRAY)
        template = cv2.imread(imgSrc, 0)
        res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
        threshold = 0.8
        loc = np.where(res >= threshold)
        if len(loc[0]) > 0:
            y = loc[0][0]
            x = loc[1][0]
            return [x, y]

    def get_store_state(self):
        x, y = [140, 1412]
        store_states_names = ['refresh', 'new_store', 'nothing', 'new_offer', 'spin_only']
        store_states = np.array([[255, 255, 255], [27, 235, 206], [63, 38, 12], [48, 253, 251], [80, 153, 193]])
        store_rgb = self.screenRGB[y:y + 1, x:x + 1]
        store_rgb = store_rgb[0][0]
        # Take mean square of rgb value and store states
        store_mse = ((store_states - store_rgb)**2).mean(axis=1)
        closest_state = store_mse.argmin()
        return store_states_names[closest_state]

    # Check if any icons are on screen
    def get_current_icons(self, new=True, available=False, dir="icons"):
        current_icons = []
        # Update screen and load screenshot as grayscale
        if new:
            self.getScreen()
        img_rgb = self.screenRGB
        img_gray = cv2.cvtColor(img_rgb, cv2.COLOR_BGR2GRAY)
        # Check every target in dir
        for target in os.listdir(dir):
            x = 0  # reset position
            y = 0
            # Load icon
            imgSrc = f'{dir}/{target}'
            template = cv2.imread(imgSrc, 0)
            # Compare images
            res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
            threshold = 0.8
            loc = np.where(res >= threshold)
            icon_found = len(loc[0]) > 0
            if icon_found:
                y = loc[0][0]
                x = loc[1][0]
            current_icons.append([target, icon_found, (x, y)])
        icon_df = pd.DataFrame(current_icons, columns=['icon', 'available', 'pos [X,Y]'])
        # filter out only available buttons
        if available:
            icon_df = icon_df[icon_df['available'] == True].reset_index(drop=True)
        return icon_df

    # Scan battle grid, update OCR images
    def scan_grid(self, new=False):
        boxes, box_size = get_grid()
        # should be enabled by default
        if new:
            self.getScreen()
        box_list = boxes.reshape(15, 2)
        names = []
        if not os.path.isdir('OCR_inputs'):
            os.mkdir('OCR_inputs')
        for i in range(len(box_list)):
            file_name = f'OCR_inputs/icon_{str(i)}.png'
            self.crop_img(*box_list[i], *box_size, name=file_name)
            names.append(file_name)
        return names

    # Take random unit in series, find corresponding dataframe and merge two random ones
    def merge_unit(self, df_split, merge_series):
        # Pick a random filtered target
        if len(merge_series) > 0:
            merge_target = merge_series.sample().index[0]
        else:
            return merge_series
        # Collect unit dataframe
        merge_df = df_split.get_group(merge_target)
        if len(merge_df) > 1:
            merge_df = merge_df.sample(n=2)
        else:
            return merge_df
        self.log_merge(merge_df)
        # Extract unit position from dataframe
        unit_chosen = merge_df['grid_pos'].tolist()
        # Send Merge
        self.swipe(*unit_chosen)
        time.sleep(0.2)
        return merge_df

    # Merge special units ['harlequin.png','dryad.png','mime.png','scrapper.png']
    # Add logging event
    def merge_special_unit(self, df_split, merge_series, special_type):
        # Get special merge unit
        special_unit, normal_unit = [
            adv_filter_keys(merge_series, units=special_type, remove=remove) for remove in [False, True]
        ]

        # Get corresponding dataframes
        special_df, normal_df = [df_split.get_group(unit.index[0]).sample() for unit in [special_unit, normal_unit]]
        merge_df = pd.concat([special_df, normal_df])
        self.log_merge(merge_df)
        # Merge 'em
        unit_chosen = merge_df['grid_pos'].tolist()
        self.swipe(*unit_chosen)
        time.sleep(0.2)
        return merge_df

    def log_merge(self, merge_df):
        merge_df['unit'] = merge_df['unit'].apply(lambda x: x.replace('.png', ''))
        unit1, unit2 = merge_df.iloc[0:2]['unit']
        rank = merge_df.iloc[0]['rank']
        log_msg = f"Rank {rank} {unit1}-> {unit2}"
        # Determine log level from rank
        if rank > 4:
            self.logger.error(log_msg)
        elif rank > 2:
            self.logger.debug(log_msg)
        else:
            self.logger.info(log_msg)

    # Find targets for special merge
    def special_merge(self, df_split, merge_series, target='zealot.png'):
        merge_df = None
        # Try to rank up dryads
        dryads_series = adv_filter_keys(merge_series, units='dryad.png')
        if not dryads_series.empty:
            dryads_rank = dryads_series.index.get_level_values('rank')
            for rank in dryads_rank:
                merge_series_dryad = adv_filter_keys(merge_series, units=['harlequin.png', 'dryad.png'], ranks=rank)
                merge_series_zealot = adv_filter_keys(merge_series, units=['dryad.png', target], ranks=rank)
                if len(merge_series_dryad.index) == 2:
                    merge_df = self.merge_special_unit(df_split, merge_series_dryad, special_type='harlequin.png')
                    break
                if len(merge_series_zealot.index) == 2:
                    merge_df = self.merge_special_unit(df_split, merge_series_zealot, special_type='dryad.png')
                    break
        return merge_df

    # Harley Merge target
    def harley_merge(self, df_split, merge_series, target='knight_statue.png'):
        merge_df = None
        # Try to copy target
        hq_series = adv_filter_keys(merge_series, units='harlequin.png')
        if not hq_series.empty:
            hq_rank = hq_series.index.get_level_values('rank')
            for rank in hq_rank:
                merge_series_target = adv_filter_keys(merge_series, units=['harlequin.png', target], ranks=rank)
                if len(merge_series_target.index) == 2:
                    merge_df = self.merge_special_unit(df_split, merge_series_target, special_type='harlequin.png')
                    break
        return merge_df
    
    # Scrapper merge
    # Will stop any merge with dps unit that's higher than rank 2
    def scrapper_merge(self, df_split, merge_target, merge_series, merge_series_with_scrapper, target='knight_statue.png'):
        merge_df = None
        # Try to copy target
        scrapper_series = adv_filter_keys(merge_series_with_scrapper, units='scrapper.png')
        if not scrapper_series.empty:
            scrapper_rank = scrapper_series.index.get_level_values('rank')
            for rank in scrapper_rank:
                # Prevent scrapper from eating merge targets above rank 2
                if target == merge_target and rank > 2:
                    break
                
                merge_series_target = adv_filter_keys(merge_series_with_scrapper, units=['scrapper.png', target], ranks=rank)

                if len(merge_series_target.index) == 2:
                    merge_df = self.merge_special_unit(df_split, merge_series_target, special_type='scrapper.png')
                    break
        return merge_df

    # Try to find a merge target and merge it
    def try_merge(self, rank=1, prev_grid=None, merge_target='zealot.png'):
        info = ''
        merge_df = None
        names = self.scan_grid(new=False)
        grid_df = bot_perception.grid_status(names, prev_grid=prev_grid)
        df_split, unit_series, df_groups, group_keys = grid_meta_info(grid_df)
        # Select stuff to merge
        merge_series = unit_series.copy()
        # Remove empty groups
        merge_series = adv_filter_keys(merge_series, units='empty.png', remove=True)
        
        if self.block_merging():
            return grid_df, unit_series, merge_series, merge_df, info
        else:
            ####### HARLEY/DRYAD #######
            if 'harlequin.png' in self.selected_units or 'dryad.png' in self.selected_units:
                # Do special merge with dryad/Harley
                self.special_merge(df_split, merge_series, merge_target)


            ####### DEMON HUNTER #######
            if merge_target == 'demon_hunter.png':
                # Use harley on DHs starting from rank 2
                self.harley_merge(df_split, merge_series, target=merge_target)
                # Keep all DHs on the board starting from rank 2
                num_dh = sum(adv_filter_keys(merge_series, ranks=[2,3,4,5,6,7], units='demon_hunter.png'))
                # Take a backup of the merge series before removing DH
                merge_series_with_dh = merge_series
                for i in range(num_dh):
                  merge_series = preserve_unit(merge_series, target='demon_hunter.png', keep_min=False)

                # Keep all demons on the board if teammate runs shaman deck
                if self.config.getboolean('bot', 'require_shaman'):
                    merge_series = adv_filter_keys(merge_series, units='demon_hunter.png', remove=True)

            ####### TRAPPER #######
            if 'trapper.png' in self.selected_units:
                # Keep highest rank trapper
                merge_series = preserve_unit(merge_series, target='trapper.png', keep_min=False)

            ####### SCRAPPER #######
            # Skip all of this if scrapper is not used
            if 'scrapper.png' in self.selected_units:
                selected_units_copy = self.selected_units.copy()
                # Backup the merge series that has the scrapper we intend to save
                # Need that one later so we can find a merge match from this backed up series
                merge_series_with_scrapper = merge_series.copy()
                # Keep lowest rank scrapper
                merge_series = preserve_unit(merge_series, target='scrapper.png', keep_min=True)

                # Start scrapping once we have enough high rank units of our merge_target on the board
                # OR if our board is getting too full
                num_merge_target = sum(adv_filter_keys(merge_series, ranks=[3,4,5,6,7], units=merge_target))
                if (num_merge_target >= 6) and (df_groups['empty.png'] <= 1):
                    # Remove merge_target from the selected_units to avoid scrapping it too early
                    selected_units_copy.remove(merge_target)
                    # Also remove scrapper ofcourse
                    selected_units_copy.remove('scrapper.png')
                    # Try to merge with any of the detected units
                    self.scrapper_merge(df_split, merge_target, merge_series, merge_series_with_scrapper, target=selected_units_copy[0])
                    self.scrapper_merge(df_split, merge_target, merge_series, merge_series_with_scrapper, target=selected_units_copy[1])
                    self.scrapper_merge(df_split, merge_target, merge_series, merge_series_with_scrapper, target=selected_units_copy[2])
                    # Try to scrap the merge target as a last resort
                    self.scrapper_merge(df_split, merge_target, merge_series, merge_series_with_scrapper, target=merge_target)

                    # If we get stuck with scrapping, specifically for DH we need to clear up some room on the board
                    # Simplest way is to allow it to merge rank 2 DH's
                    if merge_target == 'demon_hunter.png':
                        if (df_groups['empty.png'] < 1):
                            merge_series = merge_series_with_dh.copy()
                            # Remove Scrapper again
                            merge_series = preserve_unit(merge_series, target='scrapper.png', keep_min=True)
                            # Keep all DHs on the board starting from rank 3
                            num_dh = sum(adv_filter_keys(merge_series, ranks=[3,4,5,6,7], units='demon_hunter.png'))
                            for i in range(num_dh):
                                merge_series = preserve_unit(merge_series, target='demon_hunter.png', keep_min=False)

            ####### CAULDRON #######
            if 'cauldron.png' in self.selected_units:
                # Remove 4x cauldrons
                for _ in range(4):
                    merge_series = preserve_unit(merge_series, target='cauldron.png', keep_min=True)

            ####### KNIGHT STATUE #######
            if 'knight_statue.png' in self.selected_units:
                # Try to keep knight_statue numbers even (can conflict if special_merge already merged)
                num_knight = sum(adv_filter_keys(merge_series, units='knight_statue.png'))
                if num_knight % 2 == 1:
                    self.harley_merge(df_split, merge_series, target='knight_statue.png')
                # Preserve 2 highest knight statues
                for _ in range(2):
                    merge_series = preserve_unit(merge_series, target='knight_statue.png')
                
            ####### EARTH ELEMENTAL #######
            if 'earth_elemental.png' in self.selected_units:
                for _ in range(2):
                    merge_series = preserve_unit(merge_series, target='earth_elemental.png')
            
            ####### CHEMIST #######
            if 'chemist.png' in self.selected_units:
                merge_series = preserve_unit(merge_series, target='chemist.png', keep_min=False)

            ####### COLD MAGE #######
            if 'cold_mage.png' in self.selected_units:
                merge_series = preserve_unit(merge_series, target='cold_mage.png', keep_min=False)
                
            # Select stuff to merge
            merge_series = merge_series[merge_series >= 2]  # At least 2 units
            merge_series = adv_filter_keys(merge_series, ranks=7, remove=True)  # Remove max ranks
            # Try to merge high priority units
            merge_prio = adv_filter_keys(merge_series,
                                        units=['chemist.png', 'bombardier.png', 'sword.png', 'summoner.png', 'trapper.png', 'knight_statue.png'])
            if not merge_prio.empty:
                info = 'Merging High Priority!'
                merge_df = self.merge_unit(df_split, merge_prio)
            # Merge if board is getting full. Runs well with 1 also.
            if df_groups['empty.png'] <= 1:
                info = 'Merging!'
                # Add criteria
                low_series = adv_filter_keys(merge_series, ranks=rank, remove=False)
                if not low_series.empty:
                    merge_df = self.merge_unit(df_split, low_series)
                else:
                    # If grid seems full, merge more units
                    info = 'Merging high level!'
                    merge_series = adv_filter_keys(merge_series,
                                                    ranks=[3, 4, 5, 6, 7],
                                                    units=['zealot.png', 'crystal.png', 'bruser.png', merge_target],
                                                    remove=True)
                    if not merge_series.empty:
                        merge_df = self.merge_unit(df_split, merge_series)
            else:
                info = 'need more units!'
            return grid_df, unit_series, merge_series, merge_df, info

    def block_merging(self):
        if hasattr(self, 'available_icons'):
            df = self.available_icons
            # Don't merge if curse is detected
            if 'curse.png' in df['icon'].values:
                self.logger.info(f'Curse detected, not merging. Sleeping 30s')
                time.sleep(30)
                return True

            # Don't merge if Bedlam has spawned
            if 'bedlam.png' in df['icon'].values and 'bedlam_is_coming_pve.png' not in df['icon'].values and 'bedlam_is_coming_pvp.png' not in df['icon'].values:
                self.logger.info(f'Bedlam spawned, not merging. Sleeping 10s')
                time.sleep(10)
                return True
        return False

    # Mana level cards
    def mana_level(self, cards, combat, hero_power=False):
        upgrade_pos_dict = {1: [100, 1500], 2: [200, 1500], 3: [350, 1500], 4: [500, 1500], 5: [650, 1500]}
        if hasattr(self, 'available_icons'):
            df = self.available_icons
            # Don't level cards if Puppeteer has spawned
            if 'puppeteer.png' in df['icon'].values and 'puppeteer_is_coming_pve.png' not in df['icon'].values and 'puppeteer_is_coming_pvp.png' not in df['icon'].values:
                self.logger.info(f'Puppeteer spawned, not upgrading cards. Sleeping 10s')
                time.sleep(10)
            else:
                if combat > 10:
                    # Level each card
                    for card in cards:
                        self.click(*upgrade_pos_dict[card])
        if hero_power:
            self.click(800, 1500)

    # Start a dungeon floor from PvE page
    def play_dungeon(self, floor=5):
        self.logger.debug(f'Starting Dungeon floor {floor}')
        # Divide by 3 and take ceiling of floor as int
        target_chapter = f'chapter_{int(np.ceil((floor)/3))}.png'
        next_chapter = f'chapter_{int(np.ceil((floor+1)/3))}.png'
        pos = np.array([0, 0])
        avail_buttons = self.get_current_icons(available=True)
        # Check if on dungeon page
        if (avail_buttons == 'dungeon_page.png').any(axis=None):
            # Swipe to the top
            [self.swipe([0, 0], [2, 0]) for i in range(14)]
            self.click(30, 600, 5)  # stop scroll and scan screen for buttons
            # Keep swiping until floor is found
            expanded = 0
            for i in range(10):
                # Scan screen for buttons
                avail_buttons = self.get_current_icons(available=True)
                # Look for correct chapter
                if (avail_buttons == target_chapter).any(axis=None):
                    pos = get_button_pos(avail_buttons, target_chapter)
                    if not expanded:
                        expanded = 1
                        self.click_button(pos + [500, 90])
                    # check button is near top of screen
                    if pos[1] < 550 and floor % 3 != 0:
                        # Stop scrolling when chapter is near top
                        break
                elif (avail_buttons == next_chapter).any(axis=None) and floor % 3 == 0:
                    pos = get_button_pos(avail_buttons, next_chapter)
                    # Stop scrolling if the next chapter is found and last floor of chapter is chosen
                    break
                # Contiue swiping to find correct chapter
                [self.swipe([2, 0], [0, 0]) for i in range(2)]
                time.sleep(0.035)
                self.click(30, 600)  # stop scroll

            # Click play floor if found
            if not (pos == np.array([0, 0])).any():
                treasure_map_coords = self.get_treasure_map_to_click()
                if floor % 3 == 0:
                    self.click_button(pos + [30, -460])
                elif floor % 3 == 1:
                    self.click_button(pos + [30, 485])
                elif floor % 3 == 2:
                    self.click_button(pos + [30, 885])
                if treasure_map_coords is not None:
                    self.click_button(treasure_map_coords)
                self.click_button((500, 600)) # start fight
                self.wait_for_match_start()

    def play_clan_tournament(self):
        self.click_button(np.array([650, 1515])) # click clan icon
        time.sleep(1)
        self.click_button(np.array([810, 50])) # click tournament icon
        time.sleep(1)
        avail_buttons = self.get_current_icons(available=True)
        if (avail_buttons == 'sandal_available.png').any(axis=None):
            self.watch_ads() # watch tourney ad
            self.click_button(np.array([300, 1300])) # click daily battle button
            time.sleep(1)
            avail_buttons = self.get_current_icons(available=True)
            if (avail_buttons == 'sandal_play.png').any(axis=None):
                pos_sandal_button = get_button_pos(avail_buttons, 'sandal_play.png')
                self.click_button(pos_sandal_button)
                self.wait_for_match_start()
            return True
        else:
            return False
            

    def wait_for_match_start(self):
        for i in range(20):
            time.sleep(1)
            avail_buttons = self.get_current_icons(available=True)
            # Look for correct chapter
            self.logger.info(f'Waiting for match to start {i}')
            if avail_buttons['icon'].isin(['back_button.png', 'fighting.png']).any():
                break
    
    def get_treasure_map_to_click(self):
        if self.config.getboolean('bot', 'treasure_map_green') or self.config.getboolean('bot', 'treasure_map_gold'):
            df = self.get_current_icons(available=True)
            if self.config.getboolean('bot', 'treasure_map_green') and 'treasure_map_green.png' in df['icon'].values:
                df_click_green = df[df['icon'] == 'treasure_map_green.png']
                if not df_click_green.empty:
                    return (350, 1450)
            elif self.config.getboolean('bot', 'treasure_map_gold') and 'treasure_map_gold.png' in df['icon'].values and 'treasure_map_gold_is_zero.png' not in df['icon'].values:
                df_click_gold = df[df['icon'] == 'treasure_map_gold.png']
                if not df_click_gold.empty:
                    return (520, 1450)
        return None

    # Locate game home screen and try to start fight.
    def battle_screen(self, start=False, pve=True, clan_tournament=True, floor=5):
        # Scan screen for any key buttons
        self.available_icons = self.get_current_icons(available=True)
        df = self.available_icons
        if not df.empty:
            # list of buttons
            if (df == 'fighting.png').any(axis=None) and not (df == '0cont_button.png').any(axis=None):
                return df, 'fighting'
            else:
                time.sleep(1)
                self.available_icons = self.get_current_icons(available=True)
                df = self.available_icons
                if (df == 'friend_menu.png').any(axis=None):
                    self.click_button(np.array([100, 600]))
                    return df, 'friend_menu'
                # Start pvp if homescreen
                if (df == 'home_screen.png').any(axis=None) and (df == 'battle_icon.png').any(axis=None):
                    # Play clan sandals
                    if clan_tournament and start:
                        clan_tournament = self.play_clan_tournament()
                    # Start PvE
                    if pve and start and not clan_tournament:
                        self.click_button(np.array([400, 1500])) # click home screen
                        # Add a 500 pixel offset for PvE button
                        self.click_button(np.array([640, 1259]))
                        self.play_dungeon(floor=floor)
                    # Start PvP
                    elif start and not clan_tournament:
                        self.click_button(np.array([140, 1259]))
                    return df, 'home'
                # Watch ad at the end of a fight
                if (df == 'ad_fight_end.png').any(axis=None) and ((df == 'victory.png').any(axis=None)):
                    self.watch_ads()
                # Check first button is clickable
                df_click = df[df['icon'].isin(['back_button.png', 'battle_icon.png', '0cont_button.png', '1quit.png', 'item-drawer.png'])]
                if not df_click.empty:
                    button_pos = df_click['pos [X,Y]'].tolist()[0]
                    self.click_button(button_pos)
                    return df, 'menu'
        self.shell(f'input keyevent {const.KEYCODE_BACK}')  #Force back
        return df, 'lost'

    # Navigate and locate store refresh button from battle screen
    def find_store_refresh(self):
        self.click_button((100, 1500))  # Click store button
        [self.swipe([0, 0], [2, 0], menu_scrolling=True) for i in range(25)]  # swipe to top
        self.click(10, 150)  # stop scroll
        time.sleep(0.5)
        self.swipe([2, 0], [0, 0], menu_scrolling=True)  # Smaller downward swipe
        time.sleep(0.4)
        self.click(10, 150)  # stop scroll
        avail_buttons = self.get_current_icons(available=True)
        if (avail_buttons == 'refresh_button.png').any(axis=None):
            pos = get_button_pos(avail_buttons, 'refresh_button.png')
            return pos
        return False

    # Refresh items in shop when available
    def refresh_shop(self):
        if self.shop_item.size > 0:
            self.click_button((100, 1500))  # Click store button
            time.sleep(1)
            self.click_button((475, 1300))  # Click store button
            time.sleep(1)
            # Scroll up and find the refresh button
            pos = self.find_store_refresh()
            if isinstance(pos, np.ndarray):
                avail_buttons = self.get_current_icons(available=True)
                if (avail_buttons == 'shop_coin.png').any(axis=None) or (avail_buttons == 'shop_gift.png').any(axis=None) or (avail_buttons == 'shop_gift_epic.png').any(axis=None):
                    shop_item_pos_dict = {1: pos + [-200, -600], 2: pos + [100, -600], 3: pos + [385, -600], 4: pos + [-200, -170], 5: pos + [100, -170], 6: pos + [385, -170]}
                    for item in self.shop_item:
                        time.sleep(1)
                        self.click(*shop_item_pos_dict[item])
                        time.sleep(0.5)
                        avail_buttons = self.get_current_icons(available=True)
                        if (item == 1): 
                            self.logger.warning(f'Claimed free gift {item}!')
                        if (avail_buttons == 'shop_gift_claim.png').any(axis=None):
                            pos_gift_button = get_button_pos(avail_buttons, 'shop_gift_claim.png')
                            self.click_button(pos_gift_button)
                            [self.click(10, 150) for i in range(12)]
                            time.sleep(2)
                        elif (avail_buttons == 'shop_coin_buy.png').any(axis=None):
                            pos_buy_button = get_button_pos(avail_buttons, 'shop_coin_buy.png')
                            self.click_button(pos_buy_button)
                            self.logger.warning(f'Bought store item {item}!')
                            time.sleep(2)
                        self.click(10, 150)  # remove pop-up
                        time.sleep(0.5)
                # Try to refresh shop (watch ad)
                self.click_button(pos) # click refresh button
                self.logger.warning('Try to refresh shop')
                self.store_visited = True
        else:
            self.logger.warning('Skipping shop')

    def search_roulette(self):
        avail_buttons = self.get_current_icons(available=True)
        # Check if on store page
        if (avail_buttons == 'store_page.png').any(axis=None):
            # Swipe to the top
            [self.swipe([0, 0], [2, 0], menu_scrolling=True) for i in range(25)]
            self.click(10, 600, 5)  # stop scroll and scan screen for buttons
            # Keep swiping until roulette ad is found
            for i in range(6):
                # Scan screen for buttons
                avail_buttons = self.get_current_icons(available=True)
                # Look for roulette ad button
                if (avail_buttons == 'ad_roulette.png').any(axis=None):
                    self.logger.warning('Playing roulette!')
                    self.watch_ads()
                    return
                elif (avail_buttons == 'roulette_cooldown.png').any(axis=None):
                    self.logger.warning('Roulette not available yet...')
                    return
                # Continue swiping to find roulette ad button
                [self.swipe([2, 0], [0, 0], menu_scrolling=True) for i in range(4)]
                self.click(10, 600)  # stop scroll
                
    def collect_clan_chat(self):
        self.click_button(np.array([650, 1515])) # click clan icon
        time.sleep(1)
        self.click_button(np.array([260, 70])) # click clan chat icon
        time.sleep(1)
        self.click(810, 1220) # click scroll to bottom button
        time.sleep(1)
        avail_buttons = self.get_current_icons(available=True)
        self.logger.warning(f'Collecting clan chat...')
        while (avail_buttons == 'collect.png').any(axis=None) or (avail_buttons == 'collect_up.png').any(axis=None):
            time.sleep(1)
            avail_buttons = self.get_current_icons(available=True)
            if (avail_buttons == 'collect.png').any(axis=None):
                pos_collect = get_button_pos(avail_buttons, 'collect.png')
                self.click_button(pos_collect)
                [self.click(10, 600) for i in range(2)]
                time.sleep(2)
            elif (avail_buttons == 'collect_up.png').any(axis=None):
                pos_collect_up = get_button_pos(avail_buttons, 'collect_up.png')
                self.click_button(pos_collect_up)

    def request_clan_chat(self, request_epic, request_common_rare):
        self.click_button(np.array([650, 1515])) # click clan icon
        time.sleep(1)
        self.click_button(np.array([260, 70])) # click clan chat icon
        time.sleep(1)
        avail_buttons = self.get_current_icons(available=True)
        if (avail_buttons == 'clan_request_button.png').any(axis=None):
                pos = get_button_pos(avail_buttons, 'clan_request_button.png')
                self.click_button(pos)
                time.sleep(1)
                avail_buttons = self.get_current_icons(available=True)
                if not (avail_buttons == 'request.png').any(axis=None):
                    self.click(10, 600)  # click menu away
                    self.logger.warning('Request not available yet...')
                    return
                # Keep swiping until request unit is found
                for i in range(6):
                    # Scan screen for buttons
                    time.sleep(1)
                    if request_epic:
                        avail_request_units = self.get_current_icons(available=True, dir="clan_request/epic")
                        # Look for request unit
                        if (avail_request_units == request_epic).any(axis=None):
                            pos_unit = get_button_pos(avail_request_units, request_epic)
                            self.click_button(pos_unit)
                            pos_request = get_button_pos(avail_buttons, 'request.png')
                            self.click_button(pos_request)
                            self.logger.warning(f"Requested {request_epic.replace('.png', '')}")
                            return
                    if request_common_rare:
                        avail_request_units = self.get_current_icons(available=True, dir="clan_request/common_rare")
                        if (avail_request_units == request_common_rare).any(axis=None):
                            pos_unit = get_button_pos(avail_request_units, request_common_rare)
                            self.click_button(pos_unit)
                            pos_request = get_button_pos(avail_buttons, 'request.png')
                            self.click_button(pos_request)
                            self.logger.warning(f"Requested {request_common_rare.replace('.png', '')}")
                            return
                    # Continue swiping to find requested unit
                    [self.swipe([2, 0], [0, 0]) for i in range(2)]
                    time.sleep(0.5)
                    self.click(80, 600)  # stop scroll            

    def watch_ads(self):
        avail_buttons = self.get_current_icons(available=True)
        # Watch ad if available
        if (avail_buttons == 'quest_done.png').any(axis=None):
            pos = get_button_pos(avail_buttons, 'quest_done.png')
            self.click_button(pos)
            self.click(700, 600)  # collect second completed quest
            self.click(700, 400)  # collect second completed quest
            [self.click(150, 250) for i in range(2)]  # click dailies twice
            self.click(420, 420)  # collect ad chest
        elif (avail_buttons == 'ad_season.png').any(axis=None):
            pos = get_button_pos(avail_buttons, 'ad_season.png')
            self.click_button(pos)
        elif (avail_buttons == 'ad_pve.png').any(axis=None):
            pos = get_button_pos(avail_buttons, 'ad_pve.png')
            self.click_button(pos)
        elif (avail_buttons == 'ad_fight_start.png').any(axis=None):
            pos = get_button_pos(avail_buttons, 'ad_fight_start.png')
            self.click_button(pos)
        elif (avail_buttons == 'ad_fight_end.png').any(axis=None):
            pos = get_button_pos(avail_buttons, 'ad_fight_end.png')
            self.click_button(pos)
        elif (avail_buttons == 'ad_roulette.png').any(axis=None):
            pos = get_button_pos(avail_buttons, 'ad_roulette.png')
            self.click_button(pos)
        elif (avail_buttons == 'home_screen.png').any(axis=None):
            if not self.store_visited:
                self.refresh_shop()
                self.search_roulette()
        else:
            self.logger.info('Watched all ads!')
            return
        time.sleep(3)
        # Check if ad was started
        avail_buttons, status = self.battle_screen()
        if status == 'menu' or status == 'home' or (avail_buttons == 'refresh_button.png').any(axis=None):
            self.logger.info('FINISHED AD')
        # Watch ad
        else:
            self.logger.debug(f'Waiting 30s')
            time.sleep(30)
            # Keep watching until back in menu
            for i in range(10):
                avail_buttons, status = self.battle_screen()
                if status == 'menu' or status == 'home':
                    self.logger.info('FINISHED AD')
                    return  # Exit function
                time.sleep(2)
                self.click(870, 30)  # skip forward/click X
                self.click(870, 100)  # click X playstore popup
                if i > 5:
                    self.shell(f'input keyevent {const.KEYCODE_BACK}')  #Force back
                self.logger.info(f'AD TIME {i} {status}')
            # Restart game if can't escape ad
            self.restart_RR()


####
#### END OF CLASS
####


# Get fight grid pixel values
def get_grid():
    #Grid dimensions
    top_box = (153, 945)
    box_size = (120, 120)
    gap = 0
    height = 3
    width = 5
    # x_cords
    x_cord = list(range(top_box[0], top_box[0] + (box_size[0] + gap) * width, box_size[0] + gap))
    y_cord = list(range(top_box[1], top_box[1] + (box_size[1] + gap) * height, box_size[1] + gap))
    boxes = []
    # Create list of all boxes
    for y_point in y_cord:
        for x_point in x_cord:
            boxes.append((x_point, y_point))
    # Convert to np array (4x4) with x,y coords
    boxes = np.array(boxes).reshape(height, width, 2)
    return boxes, box_size


def get_unit_count(grid_df):
    df_split = grid_df.groupby("unit")
    df_groups = df_split["unit"].count()
    if not 'empty.png' in df_groups:
        df_groups['empty.png'] = 0
    unit_list = list(df_groups.index)
    return df_split, df_groups, unit_list


# Removes 1x of the highest rank unit from the merge_series
def preserve_unit(unit_series, target='trapper.png', keep_min=False):
    """
    Remove 1x of the highest rank unit from the merge_series
    param: merge_series - pandas series of units to remove
    param: target - target unit to keep
    param: keep_min - if true, keep the lowest rank unit instead of highest
    """
    merge_series = unit_series.copy()
    preserve_series = adv_filter_keys(merge_series, units=target, remove=False)
    if not preserve_series.empty:
        if keep_min:
            preserve_unit = preserve_series.index.min()
        else:
            preserve_unit = preserve_series.index.max()
        # Remove 1 count of highest/lowest rank
        merge_series[merge_series.index == preserve_unit] = merge_series[merge_series.index == preserve_unit] - 1
        # Remove 0 counts
        return merge_series[merge_series > 0]
    else:
        return merge_series


def grid_meta_info(grid_df, min_age=0):
    """
    Split grid df into unique units and ranks
    Shows total count of unit and count of each rank
    param: grid_df - pandas dataframe of grid
    param: min_age - minimum age of unit to include in meta info
    """
    # Split by unique unit
    df_groups = get_unit_count(grid_df)[1]
    grid_df = grid_df[grid_df['Age'] >= min_age].reset_index(drop=True)
    df_split = grid_df.groupby(['unit', 'rank'])
    # Count number of unit of each rank
    unit_series = df_split['unit'].count()
    #unit_series = unit_series.sort_values(ascending=False)
    group_keys = list(unit_series.index)
    return df_split, unit_series, df_groups, group_keys


def filter_units(unit_series, units):
    if not isinstance(units, list):  # Make units a list if not already
        units = [units]
    # Create temp series to hold matches
    series = []
    merge_series = unit_series.copy()
    for token in units:
        if isinstance(token, int):
            exists = merge_series.index.get_level_values('rank').isin([token]).any()
            if exists:
                series.append(merge_series.xs(token, level='rank', drop_level=False))
            else:
                continue  # skip if nothing matches criteria
        elif isinstance(token, str):
            if token in merge_series:
                series.append(merge_series.xs(token, level='unit', drop_level=False))
            else:
                continue
    if not len(series) == 0:
        temp_series = pd.concat(series)
        # Select all entries from original series that are in temp_series
        merge_series = merge_series[merge_series.index.isin(temp_series.index)]
        return merge_series
    else:
        return pd.Series(dtype=object)


def adv_filter_keys(unit_series, units=None, ranks=None, remove=False):
    """
    Returns all elements which match units and ranks values
    If one of the parameters is None, it is ignored and all values are kept
    If remove is True, all elements are removed which do not match the criteria
    param: unit_series - pandas series of units to filter
    param: units - string or list of strings of units to filter by
    param: ranks - int or list of ints of ranks to filter by
    param: remove - if true, return filtered series, if false, return only matches
    """
    # return if no units in series
    if unit_series.empty:
        return pd.Series(dtype=object)
    filtered_ranks = pd.Series(dtype=object)
    if not units is None:
        filtered_units = filter_units(unit_series, units)
    else:
        filtered_units = unit_series.copy()
    # if all units are filtered already, return empty series
    if not ranks is None and not filtered_units.empty:
        filtered_ranks = filter_units(filtered_units, ranks)
    else:
        filtered_ranks = filtered_units.copy()
    # Final filtering
    series = unit_series.copy()
    if remove:
        series = series[~series.index.isin(filtered_ranks.index)]
    else:
        series = series[series.index.isin(filtered_ranks.index)]
    return series


# Will spam read all knowledge in knowledge base for free gold, roughly 3k, 100 gems
def read_knowledge(bot):
    spam_click = range(1000)
    for i in spam_click:
        bot.click(450, 1300, 0.1)


def get_button_pos(df, button):
    #button=button+'.png'
    pos = df[df['icon'] == button]['pos [X,Y]'].reset_index(drop=True)[0]
    return np.array(pos)
