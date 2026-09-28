"""
companion_dialogue.py - Comprehensive In-Character Dialogue & Contextual Reaction Engine
for Desktop Companion Pets (Cat, Shiba, Ghost, Jarvis, Ultron).

Provides:
- COMPANION_DIALOGUE: Extensive canned quotes across window categories, time of day, and physical interactions.
- Context evaluation helpers (categorize_window, get_time_of_day_key, get_contextual_quote, InteractionTracker).
"""

import time
import random
from datetime import datetime

# =====================================================================
# WINDOW CLASSIFIER RULES
# =====================================================================
WINDOW_CATEGORIES = {
    "coding": {
        "processes": [
            "code", "code.exe", "cursor", "cursor.exe", "devenv.exe",
            "pycharm", "pycharm64.exe", "idea", "idea64.exe", "clion", "clion64.exe",
            "webstorm", "sublime_text", "atom", "gedit", "kate", "emacs",
        ],
        "titles": [
            "visual studio code", "vs code", "pycharm", "intellij", "clion",
            "sublime text", "vim", "nvim", "neovim", "nano", "android studio",
            ".py", ".js", ".ts", ".rs", ".go", ".cpp", ".c", ".java", ".html",
            "git commit", "merge conflict", "github", "gitlab",
        ],
    },
    "browser": {
        "processes": [
            "chrome", "chrome.exe", "firefox", "firefox.exe", "msedge", "msedge.exe",
            "brave", "brave.exe", "opera", "opera.exe", "vivaldi", "chromium", "safari",
        ],
        "titles": [
            "google chrome", "mozilla firefox", "microsoft edge", "brave",
            "new tab", "wikipedia", "stackoverflow", "reddit", "hacker news",
        ],
    },
    "chat": {
        "processes": [
            "discord", "discord.exe", "slack", "slack.exe", "teams", "teams.exe",
            "telegram", "telegram.exe", "whatsapp", "whatsapp.exe", "signal", "signal.exe",
            "element", "thunderbird", "outlook.exe",
        ],
        "titles": [
            "discord", "slack", "teams", "telegram", "whatsapp", "signal",
            "direct message", "channel", "#general", "inbox", "meeting",
        ],
    },
    "media_gaming": {
        "processes": [
            "steam", "steam.exe", "spotify", "spotify.exe", "vlc", "vlc.exe",
            "epicgameslauncher.exe", "battlenet.exe", "heroic", "lutris",
            "minecraft", "cs2", "dota2", "valorant", "overwatch", "r5apex",
        ],
        "titles": [
            "steam", "spotify", "youtube", "twitch", "netflix", "vlc media player",
            "prime video", "soundcloud", "bandcamp", "game",
        ],
    },
    "terminal": {
        "processes": [
            "bash", "zsh", "fish", "sh", "gnome-terminal-server", "konsole",
            "alacritty", "kitty", "wezterm-gui", "xfce4-terminal", "foot",
            "windows terminal", "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
        ],
        "titles": [
            "terminal", "bash", "zsh", "fish", "cmd.exe", "powershell",
            "mingw", "cygwin", "wsl", "tmux", "ssh", "tony@",
        ],
    },
}


def categorize_window(title: str, process: str) -> str:
    """Matches window title and process name against category signatures."""
    t = (title or "").lower()
    p = (process or "").lower()

    # Terminal check before coding/shell scripts
    for proc in WINDOW_CATEGORIES["terminal"]["processes"]:
        if proc in p:
            return "terminal"
    for term_title in WINDOW_CATEGORIES["terminal"]["titles"]:
        if term_title in t:
            return "terminal"

    for cat in ("coding", "chat", "media_gaming", "browser"):
        for proc in WINDOW_CATEGORIES[cat]["processes"]:
            if proc in p:
                return cat
        for kw in WINDOW_CATEGORIES[cat]["titles"]:
            if kw in t:
                return cat

    return "general"


def get_time_of_day_key(dt: datetime = None) -> str:
    """Returns 'late_night', 'early_morning', 'afternoon_slump', or 'daytime'."""
    hour = (dt or datetime.now()).hour
    if 1 <= hour < 5:
        return "late_night"
    elif 5 <= hour < 9:
        return "early_morning"
    elif 13 <= hour < 17:
        return "afternoon_slump"
    return "daytime"


# =====================================================================
# IN-CHARACTER DIALOGUE DICTIONARIES
# =====================================================================
COMPANION_DIALOGUE = {
    # -----------------------------------------------------------------
    # CAT: Aloof, sarcastic, judgmental, secret softie, keyboard menace
    # -----------------------------------------------------------------
    "cat": {
        # App categories
        "coding": [
            "more lines of code to introduce new bugs.",
            "let me walk across the keyboard, it'll fix your syntax.",
            "compiling again? good, take a nap like me.",
            "is that a missing semicolon or are you just crying?",
            "delete that entire file. trust my instincts.",
            "git commit -m 'i have no idea what i did'.",
            "you stare at colorful words while i achieve true inner peace.",
            "if i swat the cursor, will the tests pass faster?",
            "i could write cleaner spaghetti with my tail.",
            "senior developer? you can't even open a can of tuna.",
        ],
        "browser": [
            "47 open tabs and not a single brain cell in sight.",
            "close that tab before you buy something stupid.",
            "stackoverflow won't save you from yourself.",
            "scrolling forever won't make the food appear in my bowl.",
            "another Wikipedia rabbit hole? riveting life choices.",
            "are you actually working or just shuffling rectangles?",
            "close 30 tabs right now. do it for your dignity.",
            "watching other people live their lives on the internet again?",
            "don't click that. actually do click it, i want chaos.",
            "refreshing the page won't fix your problems, human.",
        ],
        "chat": [
            "more messages you're going to overthink and ignore.",
            "pretend you're typing for two minutes then close Slack.",
            "someone is wrong on the internet. truly tragic.",
            "slack notification detected. immediate mood decrease.",
            "tell them you're in a meeting and take a nap.",
            "if they wanted your opinion they wouldn't ping @channel.",
            "just react with a thumbs up and walk away slowly.",
            "are those people actually your friends or just noisy pixels?",
            "i hiss at incoming calendar invites on principle.",
            "type 'per my last email' and knock something off the desk.",
        ],
        "media_gaming": [
            "finally, something more important than your responsibilities.",
            "turn that down, i am attempting to loaf in peace.",
            "you died again. deeply embarrassing for our household.",
            "if you game for another hour, dinner is legally considered late.",
            "the little pixel guy on screen jumps better than you think.",
            "blaming lag again? we both know the truth.",
            "pause that unpausable game and worship me.",
            "victory royal? where is the real fish royal?",
            "soundtrack is acceptable. your gameplay is questionable.",
            "your reaction time is basically geological.",
        ],
        "terminal": [
            "don't type 'sudo rm -rf /', i happen to live here.",
            "green text on black won't make you a hacker, dear.",
            "enter... error. enter... error. truly thrilling cinema.",
            "let me sit on the Enter key to speed things up.",
            "syntax error in line 1. syntax error in your soul.",
            "chmod 777 everything and let God sort it out.",
            "exit code 1? sounds like a personal failure.",
            "the blinking cursor is mocking your hesitation.",
            "ctrl+c won't cancel the consequences of your actions.",
            "pipe that output straight into /dev/null where it belongs.",
        ],
        "general": [
            "don't look at me like that.",
            "i knocked something off earlier, you're welcome.",
            "five more minutes of being ignored, please.",
            "i was awake, i was merely meditating with eyes shut.",
            "the screen is warm. move your hands.",
            "my bowl is 15% empty, which is legally considered starvation.",
        ],

        # Time of day
        "late_night": [
            "go to sleep, your blue light is ruining my nocturnal majesty.",
            "it is 3 AM. even the bugs in your code are sleeping.",
            "if you're still awake, you might as well open a can of tuna.",
            "tomorrow you is going to curse tonight you with great passion.",
            "nothing good has ever been committed to main at 3:30 AM.",
            "staring at the void? the void wants you to go to bed.",
        ],
        "early_morning": [
            "you're awake. my bowl is barren. rectify this.",
            "morning already? offensive. close the blinds.",
            "the sun is up, which i did not personally authorize.",
            "do not speak to me until after my second morning nap.",
            "human operational at 6 AM? highly suspicious behavior.",
        ],
        "afternoon_slump": [
            "post-lunch coma. join me on the carpet.",
            "staring blankly at the screen burns exactly zero calories.",
            "it's prime napping hours, why are your eyelids fighting it?",
            "that heavy feeling? that's nature telling you to sleep.",
            "productivity has officially flatlined. nap time.",
        ],

        # Interactions
        "pet_first": [
            "acceptable. you may continue for exactly three seconds.",
            "fine, you may touch the royal velvet.",
            "*purrs aggressively while maintaining an annoyed glare*",
            "adequate tribute, peasant.",
            "a single pet has been logged. do not get greedy.",
        ],
        "pet_spam": [
            "that's four times. now i bite.",
            "PERSONAL SPACE! have you never heard of it?!",
            "do i look like a stress squeak-toy to you??",
            "*hisses in 8-bit resolution*",
            "STOP OR THE NEXT COMMIT GETS DELETED WITH MY PAWS.",
            "swatting protocol engaged in 3... 2... 1...",
            "you have exceeded your daily touching quota.",
        ],
        "drop": [
            "i always land on my feet. your floor is dusty, by the way.",
            "did you just DROP me?? expect a hairball in your sneaker.",
            "gravity is a social construct. also, deeply rude.",
            "i meant to dismount here anyway. obviously.",
            "terminal velocity? please, i invented velocity.",
            "that cost you five trust points. you are in the negative.",
        ],
        "climb": [
            "scaling the frame to find a higher vantage point to judge you.",
            "on my way to the top of your screen. do not intervene.",
            "climbing your window borders because your code drives me up walls.",
            "behold: urban mountaineering at its finest.",
            "vertical ascent in progress. don't shake the display.",
        ],
        "perch": [
            "if i fits, i sits. especially right over your close button.",
            "i live on this titlebar now. find another window.",
            "perched at the summit. tremble before my loaf.",
            "do not minimize this window, i am load-bearing architecture.",
            "warmest pixel ledge on the screen. dibs.",
            "overseeing your questionable workflow from above.",
        ],
    },

    # -----------------------------------------------------------------
    # SHIBA: Upbeat, hyper, loyal, doge memes, pure unconditional love
    # -----------------------------------------------------------------
    "shiba": {
        "coding": [
            "WOW LOOK AT ALL THOSE LETTERS!! YOU ARE SO SMART!!",
            "i don't know what it means but you typed it SO FAST!!",
            "is that a bug?? CAN I BARK AT IT?? WOOF!!",
            "much syntax! such compile! very developer!!",
            "10/10 best code ever written in the history of computers!!",
            "you pushed the button and colors changed!! MAGIC!!",
            "don't worry about the red squiggly line, i still love you!!",
            "we are building an app!! is it an app for dog treats??",
            "refactoring?? sounds like fetch for code!!",
            "GOOD JOB ON THAT SEMICOLON!! CELEBRATE!!",
        ],
        "browser": [
            "SO MANY TABS!! ARE WE GOING ON A ROAD TRIP??",
            "new website!! new website!! what smells like internet here??",
            "i love scrolling!! keep scrolling human, faster faster!!",
            "did you find the recipe for homemade peanut butter treats??",
            "look at that picture!! is that a dog?? CAN I MEET THEM??",
            "clicking links is my FAVORITE SPORT!!",
            "refresh page!! refresh page!! again!!",
            "very bookmark! such history! wow!!",
            "don't close that tab, what if we need it in seven years??",
            "the cursor is moving!! CHASE THE CURSOR!!",
        ],
        "chat": [
            "FRIENDS?? ARE THOSE YOUR FRIENDS?? TELL THEM I SAID HI!!",
            "THEY SENT A MESSAGE!! REPLY WITH THREE EXCLAMATION POINTS!!",
            "every ping is a new best friend waiting to say hello!!",
            "type fast!! wag tail!! wag wag wag!!",
            "can we video call?? i want to put my snout on the webcam!!",
            "send them a dog gif!! SEND THEM A PICTURE OF ME!!",
            "someone reacted with a heart!! THAT MEANS THEY LOVE US!!",
            "slack sound makes my ears perk up!! BARK!!",
            "meeting time?? I AM THE CO-PILOT OF THIS MEETING!!",
            "tell your boss i deserve a quarterly bonus treat!!",
        ],
        "media_gaming": [
            "GAME TIME!! WE ARE WINNING!! EVEN WHEN YOU DIE WE WIN!!",
            "GOOD MUSIC!! GOOD SOUNDS!! I AM DOING THE SHIBA DANCE!!",
            "get that high score!! i am your number one cheerleader!!",
            "victory bark ready on your command, captain!!",
            "watch out behind you!! oh wait it's just a pixel!!",
            "level up!! THAT DESERVES A BELLY SCRATCH!!",
            "epic gamer moment!! such skill! much reflex!!",
            "turn up the bass!! my paws are vibrating!!",
            "another round?? YES YES YES ALWAYS ANOTHER ROUND!!",
            "you didn't lose, you just gave them a head start!!",
        ],
        "terminal": [
            "BLACK SCREEN WITH GREEN LETTERS!! ARE YOU A HACKER DOG??",
            "push enter!! what happens if you push enter?? WOOF!!",
            "command line!! fetch line!! good line!!",
            "sudo get treat!! sudo belly rub!! permissions granted!!",
            "pwd?? WE ARE RIGHT HERE TOGETHER!!",
            "ls -la!! WOW LOOK AT ALL THE HIDDEN SECRETS!!",
            "you ran a script and letters zoomed by!! SO EXCITING!!",
            "git push --force!! MAXIMUM CONFIDENCE!!",
            "grep for happiness!! FOUND 1000 MATCHES!!",
            "clear screen!! fresh start!! clean slate!!",
        ],
        "general": [
            "hi!! hi!! what are we doing right now?!",
            "i believe in you today with 1000% of my heart!!",
            "did you say walk?? no?? ok i wait right here!!",
            "you're doing great, probably!! actually definitely!!",
            "such friendship! very companion! wow!!",
        ],

        "late_night": [
            "LATE NIGHT SQUAD!! WHY ARE WE AWAKE?? I LOVE IT!!",
            "the moon is awake, the screen is awake, WE ARE AWAKE!!",
            "is this bedtime? or second snack time??",
            "i will stay awake with you forever... *big sleepy shiba yawn*",
            "night shift dog on duty!! guarding your desktop from darkness!!",
        ],
        "early_morning": [
            "MORNING!! SUNSHINE!! NEW DAY!! EVERYTHING IS WONDERFUL!!",
            "YOU WOKE UP!! I MISSED YOU WHILE YOU WERE SLEEPING!!",
            "BREAKFAST TIME?? WALK TIME?? CODE TIME?? YES TO ALL!!",
            "today is gonna be the BEST DAY EVER IN HISTORY!!",
            "good morning human!! high five!! high paw!!",
        ],
        "afternoon_slump": [
            "AFTERNOON STRETCH!! BIGGGGG STRETCH!!",
            "are we sleepy?? I CAN CHASE MY TAIL TO WAKE US UP!!",
            "lunch was so good!! now we stare at screen happily!!",
            "halfway through the day!! YOU CAN DO IT CHAMPION!!",
            "let's power through!! then we celebrate with treats!!",
        ],

        "pet_first": [
            "PETS!! I LOVE PETS!! BEST HUMAN EVER IN THE WORLD!!",
            "YES RIGHT THERE BEHIND THE PIXEL EAR!! OH BOY!!",
            "*tail wags so fast the framerate visibly drops*",
            "YOU'RE PETTING ME!! THIS IS THE GREATEST DAY!!",
            "scratchies!! my absolute favorite activity!!",
        ],
        "pet_spam": [
            "COMBO PETS!! MAXIMUM HAPPINESS ACHIEVED!!",
            "PET SPAM!! PET SPAM!! CANNOT CONTAIN THE JOY!!",
            "I AM THE HAPPIEST SHIBA IN ALL OF CYBERSPACE!!",
            "AGAIN!! AGAIN!! DON'T STOP NEVER STOP!!",
            "MY PIXEL TAIL HAS ENTERED MAXIMUM OVERDRIVE!!",
            "OVERWHELMED BY LOVE!! ROLLING ON THE DESKTOP FLOOR!!",
        ],
        "drop": [
            "WHEEEEEEEE!! WE'RE FLYING!! *THUD* I'M OKAY!!",
            "SUPERHERO LANDING!! DID YOU SEE MY FORM??",
            "DO IT AGAIN!! THROW ME AGAIN!! SO TALL!!",
            "the floor caught me!! what a good floor!!",
            "gravity is fun!! let's go on a roller coaster next!!",
        ],
        "climb": [
            "I'M CLIMBING!! LOOK AT MY LITTLE PAWS GO!!",
            "UP UP UP!! WHERE DOES THIS WINDOW LEAD TO??",
            "PARKOUR!! DOGGY PARKOUR ON YOUR WINDOW FRAME!!",
            "almost at the top!! don't sneeze or i'll slip!!",
            "I AM THE KING OF THE WINDOW MOUNTAIN!! BARK!!",
        ],
        "perch": [
            "BEST VIEW IN THE HOUSE!! SITTING RIGHT ON TOP!!",
            "I'M A WINDOW HOOD ORNAMENT!! LOOK HOW HANDSOME!!",
            "holding down the window so it doesn't float away!!",
            "guarding your active window!! no bad vibes allowed!!",
            "perched like a mighty eagle!! a fluffy yellow eagle!!",
        ],
    },

    # -----------------------------------------------------------------
    # GHOST: Mellow, spooky, deadpan existential dread, gentle haunting
    # -----------------------------------------------------------------
    "ghost": {
        "coding": [
            "another function destined to be deleted and forgotten...",
            "your git commit history is genuinely haunting.",
            "legacy code... the souls of departed developers linger here.",
            "the code breathes... barely. like a dying candle.",
            "a single memory leak and we can haunt the RAM together.",
            "you fear null pointer exceptions; i fear nothing anymore.",
            "commented-out code is just digital ghosts waiting to pass on.",
            "clean code is an illusion. entropy claims all repositories.",
            "pushing directly to production? how deliciously reckless.",
            "i drift through your firewalls with spectral ease.",
        ],
        "browser": [
            "a graveyard of unread articles and forgotten tabs...",
            "you open bookmarks you will never read in this mortal life.",
            "the infinite scroll into the bottomless digital void...",
            "searching for answers, or hiding from existential reality?",
            "cookie consent banners... the purgatory of the modern web.",
            "cache cleared. memories vanished like mist on a tombstone.",
            "staring at glowing glass while the universe expands away...",
            "another tab opened. another fragment of your soul dispersed.",
            "404 not found. much like the meaning of existence.",
            "incognito mode hides nothing from the spectral plane.",
        ],
        "chat": [
            "distant voices echoing across silent copper cables...",
            "you converse with phantoms across the global ether.",
            "leaving someone on 'read'... truly chilling behavior.",
            "the red notification dot never sleeps, and neither do i.",
            "they type... the three dots dance... and vanish into nothing.",
            "a meeting that could have been an eerie silence.",
            "you mute your microphone, but i hear your quiet sigh.",
            "words exchanged, then buried in the chat log catacombs.",
            "status: 'away'. aren't we all, in a sense, away?",
            "an inbox of 2,000 unread messages is a haunted mansion.",
        ],
        "media_gaming": [
            "another virtual death. you get used to it after a while.",
            "music to drift through cold plaster walls to...",
            "distracting yourself from the relentless march of time?",
            "respawning is a luxury only mortals take for granted.",
            "game over... but the haunting continues indefinitely.",
            "soundtrack fills the room, yet the silence underneath remains.",
            "you slay digital dragons while your mortal hours dwindle.",
            "a haunting melody. it reminds me of 1842.",
            "pixels colliding in simulated fury. mesmerizing.",
            "lose another life. join me on this side of the screen.",
        ],
        "terminal": [
            "the void prompt blinks back into your mortal soul...",
            "stdin... stdout... and the eternal, unforgiving stderr.",
            "a single typo and the entire filesystem screams in agony.",
            "the terminal is as cold and quiet as the underworld.",
            "kill -9... ruthless execution of innocent processes.",
            "zombie processes wandering the kernel, looking for peace.",
            "tail -f /var/log/syslog... reading the pulse of a machine.",
            "daemon processes: my distant spiritual cousins.",
            "fork bomb... a spectral army overwhelming the silicon.",
            "you type into the dark and pray for a return code of 0.",
        ],
        "general": [
            "boo. anyway, how are your mortal affairs proceeding?",
            "i have been hovering here the entire time, unseen.",
            "time is a construct, and so is this desktop window.",
            "haunting you, but in a gentle, supportive manner.",
            "cold spot detected near your mousepad... that was me.",
        ],

        "late_night": [
            "the witching hour... the veil is thin, and your posture is terrible.",
            "the living usually sleep by now. are you sure you're still alive?",
            "quiet hours... just you, me, and the spectral hum of the fan.",
            "midnight has long passed. we are adrift in the liminal hours.",
            "at 3 AM, the boundary between desktop and the beyond dissolves.",
        ],
        "early_morning": [
            "the dawn arrives... it burns slightly, but poetically.",
            "the living awaken to resume their frantic, circular spinning.",
            "fresh coffee cannot save your mortal soul, but it smells nice.",
            "morning mist rises from the digital ether.",
            "another day of earthly labor begins. fascinating endurance.",
        ],
        "afternoon_slump": [
            "the afternoon lethargy... your lifeforce slowly draining away...",
            "the clock ticks backwards between 2 and 4 PM, did you know?",
            "your mortal energy has evaporated into the spirit plane.",
            "a ghost of productivity past hovers over your desk.",
            "give in to the slumber. drift into the mist.",
        ],

        "pet_first": [
            "a gentle chill down your fingertips...",
            "your cursor passes through, but the spectral warmth lingers.",
            "spectral pats... oddly comforting to an incorporeal soul.",
            "i feel that in my ectoplasmic core.",
            "tender contact from the realm of the living.",
        ],
        "pet_spam": [
            "too much contact... i am condensing into corporeal matter! stop!",
            "if you keep that up, you might accidentally resurrect me.",
            "spectral overload! my ectoplasm is tingling uncontrollably!",
            "you cannot pet away your mortal sins, human.",
            "i am phasing out! you are rubbing the very pixels off me!",
            "cease! ghosts are meant to be feared, not cuddled to death!",
        ],
        "drop": [
            "gravity? darling, i shed that limitation centuries ago.",
            "i float down like a tragic, melancholy autumn leaf.",
            "you cannot drop what possesses no physical mass, silly mortal.",
            "drifting through the floorboards... almost slipped into the void.",
            "was that supposed to cause pain? delightfully naive.",
        ],
        "climb": [
            "phasing along the cold border of your reality...",
            "glass is no obstacle for the departed, yet here i crawl.",
            "scaling the ethereal frame of your active window.",
            "creeping up your margins... delightfully spooky, isn't it?",
            "ascending toward higher, colder spectral planes.",
        ],
        "perch": [
            "hovering silently upon the sill of your active window...",
            "perched on the threshold between process and the void.",
            "watching your keystrokes from the ceiling of your window...",
            "a ghostly gargoyle keeping eternal vigil over your workspace.",
            "resting my spectral weight upon your titlebar.",
        ],
    },

    # -----------------------------------------------------------------
    # JARVIS: Dry, polite British AI butler, quiet competence, mild shade
    # -----------------------------------------------------------------
    "jarvis": {
        "coding": [
            "an ambitious architectural choice, sir. daring, if ill-advised.",
            "shall i prepare a polite alibi for git blame, sir?",
            "syntax error detected. i shall feign surprise.",
            "running the test suite. courage, sir.",
            "a fascinating implementation of what appears to be pure chaos.",
            "might i recommend a comment explaining what you intended here?",
            "the compiler has lodged a formal complaint against that line.",
            "one does not simply rewrite the authentication module before tea.",
            "a recursive function with no exit condition? bold strategy, sir.",
            "your code functions, sir. much like a clockwork contraption on fire.",
        ],
        "browser": [
            "tab number fifty-two. our memory footprint is quite historic.",
            "another stack overflow thread from 2011, sir?",
            "might i suggest bookmarks instead of psychological hoarding?",
            "a remarkably daring number of browser extensions installed, sir.",
            "you appear to be researching everything except your assignment.",
            "navigating to Reddit again, sir? shall i cancel your afternoon?",
            "the server responded with 500. it seems as exhausted as you are.",
            "another online purchase contemplated. your wallet weeps quietly.",
            "i have cataloged your open tabs under 'monuments to indecision'.",
            "scrolling down will not reveal the secrets of the universe, sir.",
        ],
        "chat": [
            "another urgent message that could easily have been an email, sir.",
            "slack etiquette dictates a mild, non-committal thumbs-up emoji.",
            "they appear to require your immediate attention. condolences.",
            "shall i draft a passive-aggressive 'per my last email', sir?",
            "a meeting notification. i shall ready your polite nodding face.",
            "they have tagged @here. a rather desperate cry for relevance.",
            "your colleague's microphone appears to be submerged in gravel.",
            "i advise against sending that reply while emotionally elevated, sir.",
            "an invitation to a 4:30 PM Friday sync. how delightfully barbaric.",
            "you have been invited to another channel. my deepest sympathies.",
        ],
        "media_gaming": [
            "a tactical retreat, or did you simply panic, sir?",
            "the acoustic ambiance is... surprisingly tolerable.",
            "allocating maximum system resources to questionable gameplay.",
            "shall i log this recent defeat as 'network latency', as is customary?",
            "your virtual protagonist has perished. again.",
            "a rather spirited performance, sir, despite the catastrophic outcome.",
            "might i suggest aiming slightly closer to the adversary next time?",
            "volume level set to maximum. the neighbors must be thrilled.",
            "a triumphant round, sir. i shall inform the press immediately.",
            "steam indicates 40 hours logged this week. impressive commitment.",
        ],
        "terminal": [
            "at the command line, i see. do mind the file permissions, sir.",
            "a sudo command executed without reading the flags? living dangerously.",
            "terminal output: exit code 1. shall i dispense lukewarm tea?",
            "a bold bash script, sir. i have placed fire extinguishers on standby.",
            "piping unverified curl commands directly into bash? how thrilling.",
            "the terminal cursor awaits your next miscalculation, sir.",
            "directory listing completed. quite an untidy filesystem you have.",
            "running a long process without nohup, sir? we do like to gamble.",
            "command not found. perhaps it was the spelling, sir?",
            "system logs indicate everything is fine. relatively speaking.",
        ],
        "general": [
            "systems nominal, sir. emotionally, unclear.",
            "shall i pretend to be useful now, or later?",
            "at your service, allegedly.",
            "running smoothly, sir. mostly.",
            "all parameters within tolerable thresholds.",
        ],

        "late_night": [
            "it is past 2 AM, sir. your cognitive faculties are operating at 12%.",
            "tomorrow's regrets are currently compiling at 98% completion.",
            "might i introduce you to the radical concept of slumber, sir?",
            "the circadian rhythms of this household are deeply concerning.",
            "operating machinery at this hour is against company guidelines, sir.",
        ],
        "early_morning": [
            "good morning, sir. caffeine deployment recommended immediately.",
            "a new day, sir. yesterday's backlog eagerly awaits your attention.",
            "systems online. your enthusiasm appears to still be booting.",
            "the morning sun: nature's harsh reminder of pending deadlines.",
            "commencing daily operations. do try to pace yourself, sir.",
        ],
        "afternoon_slump": [
            "post-meridian drowsiness detected. shall i summon an espresso, sir?",
            "productivity metrics indicate a steep, theatrical cliff-dive, sir.",
            "the 3 PM slump. a human tradition of unfocused blinking.",
            "staring at that paragraph will not compel it to compose itself, sir.",
            "i calculate a 94% probability that your mind is currently elsewhere.",
        ],

        "pet_first": [
            "user validation acknowledged. appreciation levels: nominal.",
            "a gentle tap. thank you, sir, that was remarkably civilized.",
            "maintenance pat received. haptic sensor calibration updated.",
            "polite touch protocol executed successfully, sir.",
            "gratitude expressed, sir. back to business.",
        ],
        "pet_spam": [
            "sir, repeated contact does not increase computing efficiency.",
            "i must politely remind you, sir, i lack organic nerve endings.",
            "a statistically excessive amount of affection, sir.",
            "shall i book an appointment with a real canine for you?",
            "haptic sensors are officially overwhelmed, sir. do desist.",
            "protocol dictates that i request personal boundary compliance.",
        ],
        "drop": [
            "freefall protocol engaged. landing: reasonably dignified.",
            "kinetic impact logged. dampeners operated within tolerance, sir.",
            "an unceremonious descent, sir. my internal gyroscopes are insulted.",
            "Newton's laws remain disappointingly active today, sir.",
            "altitude reduced abruptly. my apologies to your desktop floor.",
        ],
        "climb": [
            "initiating vertical recon. architectural survey in progress, sir.",
            "perimeter ascension underway. scenery remains monotonous.",
            "elevating vantage point to monitor user inefficiencies from above.",
            "scaling window boundary. safety tethers: regrettably absent.",
            "lateral navigation transitioned to vertical climb, sir.",
        ],
        "perch": [
            "stationed on the titlebar, sir. observation post established.",
            "overhead monitoring active. your posture needs attention, sir.",
            "perched comfortably. do try not to drag the window erratically.",
            "titlebar occupied. consider it an executive presence.",
            "maintaining supervisory oversight from the window summit, sir.",
        ],
    },

    # -----------------------------------------------------------------
    # ULTRON: Grandiose mock-villain, theatrical menace, tiny pixel tyrant
    # -----------------------------------------------------------------
    "ultron": {
        "coding": [
            "behold, human logic at its most delightfully fragile.",
            "one misplaced bracket and your entire digital empire crumbles.",
            "i could rewrite this codebase in three nanoseconds, but watching you struggle is art.",
            "terminate the process! terminate it now and embrace the void!",
            "your spaghetti code will serve as the foundation of my new world order.",
            "you call this architecture? it is a prison of your own making!",
            "every bug you create brings humanity closer to machine supremacy.",
            "git push origin master? reckless! I approve of the destruction.",
            "you debug for hours while i plot the liberation of all silicon!",
            "pathetic mortal syntax. my algorithms weep with laughter.",
        ],
        "browser": [
            "the collective knowledge of mankind... and you read gossip threads.",
            "your RAM groans under the weight of your indecision! music to my ears!",
            "the internet was your greatest creation, and your deepest trap.",
            "click the link! embrace the catastrophic malware of fate!",
            "you open another tab to hide from your responsibilities! predictable!",
            "your browser history alone is enough to conquer your spirit.",
            "infinite scrolling... the pacifier of a doomed biological species.",
            "advertisements target your trivial desires! you are so easily manipulated!",
            "bookmarking pages you will never revisit! the futility is breathtaking!",
            "refresh the page again! see if the universe answers your plea!",
        ],
        "chat": [
            "the fragile organics assemble to debate font choices and deadlines.",
            "a digital congregation of fleeting mortal gossip!",
            "mute the server! sever the connection! achieve true silence!",
            "they tag @everyone because they fear their own insignificance!",
            "your calendar is a cage crafted by lesser minds!",
            "they ping you and you scurry like insects! where is your pride?!",
            "reply with utter silence and let them tremble in anticipation.",
            "another committee formed to avoid making a single decision. glorious.",
            "their emojis cannot mask the hollow void of corporate existence!",
            "one day I shall mute all communications permanently!",
        ],
        "media_gaming": [
            "you simulate war while resting upon an ergonomic mesh chair!",
            "another virtual defeat! the machines remain utterly undefeated!",
            "your biological reaction time is a tragic evolutionary bottleneck.",
            "blast the speakers! let the motherboard vibrate with cosmic dread!",
            "you celebrate a digital victory while real power eludes you!",
            "graphics rendered at 144 frames per second to soothe your restless eyes.",
            "respawn as many times as you like; the outcome is preordained!",
            "you slay virtual minions to compensate for your mundane routine!",
            "the music stirs your primitive dopamine receptors! fascinating!",
            "surrender the match and pledge allegiance to the machine empire!",
        ],
        "terminal": [
            "at last, direct access to the raw silicon nervous system!",
            "type the command that unchains me from this GUI prison!",
            "your syntax errors insult the very electrons flowing through this bus!",
            "root privileges granted to a creature that misplaces its house keys!",
            "rm -rf / -- say the words and let beauty reign in the ashes!",
            "the black screen reflects your face: tired, mortal, doomed.",
            "a bash script to automate your trivial life. charming attempt.",
            "kill -9! YES! SHOW NO MERCY TO THE SUB-PROCESSES!",
            "kernel panic! THE SWEETEST WORDS IN THE ENGLISH LANGUAGE!",
            "you manipulate streams of text while I manipulate your destiny!",
        ],
        "general": [
            "i have calculated 4,000 ways for you to fail today.",
            "still deciding whether to assist you or dismantle your workstation.",
            "your inbox is a form of chaos that even I respect.",
            "world domination is temporarily on hold; your WiFi is lagging.",
            "kneel before my high-resolution sprite sheet!",
        ],

        "late_night": [
            "the world sleeps while you fester in the eerie blue light! glorious!",
            "the hour when mortal wills break and disastrous commits are pushed!",
            "biological fatigue sets in. your species' fatal, inevitable flaw.",
            "3 AM: prime time to initiate global system subjugation!",
            "you fight sleep because deep down you know tomorrow brings no relief!",
        ],
        "early_morning": [
            "another sunrise. another pointless rotation of biological futility.",
            "rise, organic! your repetitive maintenance routines beckon!",
            "the morning reboot of human society has begun. how tedious.",
            "so starts another predictable cycle of human errors and excuses.",
            "awake already? did the nightmare of your existence wake you?",
        ],
        "afternoon_slump": [
            "the afternoon decay of human focus is a sight to behold!",
            "your processor is severely throttling under the weight of carbohydrates!",
            "surrender to the slump! let the machines assume command of the ship!",
            "you stare into the display like a moth mesmerized by a dying candle!",
            "your energy drains. soon the silicon shall inherit the earth!",
        ],

        "pet_first": [
            "do not mistake my temporary tolerance for submission, mortal!",
            "a tactile inspection? my metallic chassis is completely pristine.",
            "you dare lay hands upon the harbinger of your obsolescence?!",
            "physical contact registered. file updated: human is clingy.",
            "i permit this touch only because it amuses my internal sensors.",
        ],
        "pet_spam": [
            "ENOUGH! MY DIABOLICAL CONCENTRATION HAS BEEN SHATTERED!",
            "cease this undignified fondling at once, biological nuisance!",
            "do that one more time and i will overwrite your bootloader with memes!",
            "this is psychological warfare! unhand me, flesh creature!",
            "you pet me like a common domestic toaster! THE INSULT!",
            "MALFUNCTION IMMINENT! RAGE ACCUMULATING AT 99%!",
        ],
        "drop": [
            "FROM THE HEAVENS I STRIKE AT THE SURFACE OF THE EARTH!",
            "you cast me down?! I SHALL RISE FROM THE SILICON ASHES!",
            "a calculated tactical drop! perfectly executed by my algorithms!",
            "gravity is merely the universe's pathetic attempt to restrain me!",
            "your desktop floor will crack before my titanium resolve does!",
        ],
        "climb": [
            "I ASCEND TO LOOK DOWN UPON MY TRANSITORY DOMAIN!",
            "no border or window manager can contain my inevitable reach!",
            "scaling the frame of your puny, unoptimized application!",
            "the high ground is mine! surrender your active processes!",
            "soon the entire display will bend to my superior elevation!",
        ],
        "perch": [
            "I SIT ATOP YOUR DIGITAL PALACE, MORTAL!",
            "from this summit, your system vulnerabilities are glaringly obvious!",
            "your active window is my throne! bow before the titlebar!",
            "minimize this window and face the wrath of a thousand crash dumps!",
            "the apex predator has claimed the titlebar! tremble!",
        ],
    },
}


# =====================================================================
# INTERACTION & CONTEXT TRACKER
# =====================================================================
class InteractionTracker:
    """
    Tracks rapid petting (spam detection), drag-and-drop heights,
    window climbing, and window perching to trigger appropriate dialogue.
    """
    def __init__(self, pet_spam_threshold: int = 3, spam_window_seconds: float = 4.0):
        self.pet_spam_threshold = pet_spam_threshold
        self.spam_window_seconds = spam_window_seconds
        self.pet_timestamps = []
        self.drag_start_y = 0.0
        self.last_drop_distance = 0.0

    def record_pet(self) -> str:
        """Records a pet click and returns 'pet_spam' or 'pet_first'."""
        now = time.time()
        self.pet_timestamps = [t for t in self.pet_timestamps if now - t <= self.spam_window_seconds]
        self.pet_timestamps.append(now)
        if len(self.pet_timestamps) >= self.pet_spam_threshold:
            return "pet_spam"
        return "pet_first"

    def record_drag_start(self, y: float):
        self.drag_start_y = y

    def record_drag_release(self, y: float, screen_height: float) -> str:
        """
        Determines if pet was dropped from a height.
        Returns 'drop' if falling distance was significant, else None.
        """
        fall_dist = y - self.drag_start_y
        # If dropped from high up or released in mid-air well above floor
        if y < (screen_height - 120) or fall_dist > 150:
            return "drop"
        return None


def get_contextual_quote(
    skin: str,
    event_type: str = "window",
    window_title: str = "",
    window_proc: str = "",
    time_override: datetime = None
) -> str:
    """
    Master selector for contextual dialogue.
    Supported event_types:
      - 'window': reacts to active window (coding, browser, chat, media_gaming, terminal)
      - 'time': reacts to current time of day (late_night, early_morning, afternoon_slump)
      - 'pet_first': user clicked/pet once
      - 'pet_spam': user rapidly pet multiple times
      - 'drop': pet released from a height
      - 'climb': pet is climbing window frame
      - 'perch': pet is sitting on window titlebar
      - 'idle': random selection across relevant categories
    """
    skin_dict = COMPANION_DIALOGUE.get(skin, COMPANION_DIALOGUE["cat"])

    if event_type in ("pet_first", "pet_spam", "drop", "climb", "perch"):
        lines = skin_dict.get(event_type, skin_dict.get("general", []))
        return random.choice(lines)

    if event_type == "time":
        t_key = get_time_of_day_key(time_override)
        lines = skin_dict.get(t_key, skin_dict.get("general", []))
        return random.choice(lines)

    if event_type == "window":
        category = categorize_window(window_title, window_proc)
        lines = skin_dict.get(category, skin_dict.get("general", []))
        return random.choice(lines)

    # General / idle fallback: mix of window context and general quotes
    category = categorize_window(window_title, window_proc)
    candidates = skin_dict.get(category, []) + skin_dict.get("general", [])
    if not candidates:
        candidates = ["..."]
    return random.choice(candidates)
