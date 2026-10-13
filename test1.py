import random
import string
import time
import keyboard


# ============================================================
# CONFIGURATION
# ============================================================

TYPING_HOURS = 1       # 1 = 1 hour, 2 = 2 hours, 3 = 3 hours
MIN_DELAY = 0.04
MAX_DELAY = 0.16


# ============================================================
# HUMAN-LIKE TYPING
# ============================================================

def human_like_typing(text):
    """Type text with variable speed and natural pauses."""

    for char in text:

        # Space between words
        if char == " ":
            keyboard.write(char)
            time.sleep(random.uniform(0.08, 0.35))

            # Occasional thinking pause
            if random.random() < 0.12:
                time.sleep(random.uniform(0.5, 1.5))

            continue

        keyboard.write(char)

        # Punctuation pauses
        if char in ".!?":
            time.sleep(random.uniform(0.5, 1.3))

        elif char in ",;:":
            time.sleep(random.uniform(0.2, 0.6))

        else:
            # Variable typing speed
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        # Occasional longer pause
        if random.random() < 0.03:
            time.sleep(random.uniform(0.6, 2.0))


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    total_seconds = TYPING_HOURS * 60 * 60

    print(f"Typing duration: {TYPING_HOURS} hour(s)")
    print("Switch to the target window.")
    print("Starting in 5 seconds...")

    time.sleep(5)

    start_time = time.time()

    sample_text = (
        "Hi, I have completed the work. "
        "Please review it once and let me know if anything needs to be changed."
    )

    while time.time() - start_time < total_seconds:

        human_like_typing(sample_text)

        # Pause between typing sessions
        time.sleep(random.uniform(2, 8))

    print("Typing duration completed.")