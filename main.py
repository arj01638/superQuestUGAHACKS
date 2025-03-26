import threading
import random
import re
import logging
from time import sleep

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

import g4f

logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.DEBUG)

# Global configuration
FONT_NAME = 'Bangers.ttf'
g4f.debug.logging = True
g4f.debug.version_check = False

# Log provider info
logger.debug("Provider You params: %s", g4f.Provider.You.params)
logger.debug("Working Providers: %s", [
    provider.__name__
    for provider in g4f.Provider.__providers__
    if provider.working
])

provider = g4f.Provider.You
model = g4f.models.gpt_4


def create_chat_completion_with_retry(*args, **kwargs):
    """Creates a chat completion with retry logic (3 attempts)."""
    for _ in range(3):
        try:
            return g4f.ChatCompletion.create(*args, **kwargs)
        except Exception as e:
            logger.debug("Error: %s. Retrying...", e)
        sleep(5)
    raise Exception("Failed to create chat completion after 3 attempts")


def generate_prompt():
    """Generates a game prompt composed of power and scenario prompts."""
    if random.random() < 0.3:
        logger.debug("Using stock powers")
        with open("stockpowers.txt", "r") as f:
            power_prompts = f.read().split("\n\n")
            power_prompt = random.choice(power_prompts)
    else:
        logger.debug("Using dynamic powers")
        with open("powerprompt.txt", "r") as f:
            power_prompt_text = f.read()
            power_prompt = create_chat_completion_with_retry(
                model=model,
                provider=provider,
                messages=[{"role": "user", "content": power_prompt_text}],
            )
            banned_powers = ["shadow", "memory", "echo"]
            while any(banned in power_prompt.lower() for banned in banned_powers):
                logger.debug("Regenerating power prompt... (%s)", power_prompt)
                power_prompt = create_chat_completion_with_retry(
                    model=model,
                    provider=provider,
                    messages=[{"role": "user", "content": power_prompt_text}],
                )

    logger.debug("\nPower prompt: %s\n", power_prompt)

    if random.random() < 0.2:
        logger.debug("Using scenario w/o powers mentioned")
        with open("scenarioprompt.txt", "r") as f:
            scenario_prompt_text = f.read()
            scenario_prompt = create_chat_completion_with_retry(
                model=model,
                provider=provider,
                messages=[{"role": "user", "content": scenario_prompt_text}],
            )
    else:
        logger.debug("Using scenario w/ powers mentioned")
        with open("scenariopromptwithpower.txt", "r") as f:
            scenario_prompt_text = (
                f.read() + power_prompt +
                "\n Remember, do not write about what the user does, just post a scenario prompt for them to solve. "
                "Do not even give suggestions for how they might solve it."
            )
            logger.debug("\n\n%s\n\n", scenario_prompt_text)
            scenario_prompt = create_chat_completion_with_retry(
                model=model,
                provider=provider,
                messages=[{"role": "user", "content": scenario_prompt_text}],
            )

    logger.debug("\nScenario prompt: %s\n", scenario_prompt)
    return power_prompt + "\n\n" + scenario_prompt


def generate_response(conversation):
    """Generates a response based on the conversation history."""
    # Get weaknesses
    response = create_chat_completion_with_retry(
        model=model,
        provider=provider,
        messages=conversation + [{
            "role": "user",
            "content": (
                "What are the weaknesses of the plan proposed by the user in the previous message? "
                "Only go off of what the user said. Be brief. Limit word count. Do not use markdown."
            )
        }],
    )
    weaknesses = response
    logger.debug("\nWeaknesses: %s\n", weaknesses)

    # Get percentage odds
    response = create_chat_completion_with_retry(
        model=model,
        provider=provider,
        messages=conversation + [{
            "role": "user",
            "content": (
                "Here are some potential weaknesses of the user's plan: " + weaknesses +
                "\n\nWhat are the odds this works? Do not write anything but a percentage number estimating "
                "the chance whether it works or not. Begin your reply with \"Percentage: \" and then the number. "
                "Do not write anything else."
            )
        }],
    )
    logger.debug(response)
    percentage = float(re.findall(r"\d+\.?\d*", response)[0])
    logger.debug("\nPercentage: %s\n", percentage)

    # Generate success or failure narrative
    if random.random() < percentage / 100.0:
        response = create_chat_completion_with_retry(
            model=model,
            provider=provider,
            messages=conversation + [{
                "role": "user",
                "content": (
                    "Write what happens next in the second person knowing this plan succeeds. "
                    "Be brief. Limit word count. Do not use markdown."
                )
            }],
        )
        logger.debug("\nSuccess: %s\n", response)
    else:
        response = create_chat_completion_with_retry(
            model=model,
            provider=provider,
            messages=conversation + [{
                "role": "user",
                "content": (
                    "Here are some potential weaknesses of the user's plan: " + weaknesses +
                    "\n\nWrite what happens next in the second person knowing this plan fails. "
                    "Be brief. Limit word count. Do not use markdown."
                )
            }],
        )
        logger.debug("\nFailure: %s\n", response)
    return response


def check_success(conversation):
    """Checks if the scenario has been resolved successfully."""
    response = create_chat_completion_with_retry(
        model=model,
        provider=provider,
        messages=conversation + [{
            "role": "user",
            "content": "Has this scenario been resolved successfully? Do not write anything other than \"yes\" or \"no\"."
        }],
    )
    return "yes" in response.lower()


def check_failure(conversation):
    """Checks if the scenario has ended in complete failure."""
    response = create_chat_completion_with_retry(
        model=model,
        provider=provider,
        messages=conversation + [{
            "role": "user",
            "content": "Has the user completely failed the scenario with no way out? Do not write anything other than \"yes\" or \"no\"."
        }],
    )
    return "yes" in response.lower()


class RoundedTextInput(TextInput):
    background_color = (0.9, 0.9, 0.9, 1)
    background_normal = 'rounded.png'
    background_active = 'rounded.png'


class Console(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.conversation = []
        self.game_over = False

        # Background
        with self.canvas.before:
            self.rect = Rectangle(source='gradient.png', size=self.size, pos=self.pos)
        self.bind(size=self._update_rect, pos=self._update_rect)

        # Console text area
        self.console_text = TextInput(
            readonly=True,
            halign='left',
            multiline=True,
            padding_y=[0, 0],
            size_hint=(1, 0.7),
            pos_hint={'x': 0, 'y': 0.3},
            font_size=22,
            background_color=(0, 0, 0, 0.4),
            foreground_color=(1, 1, 1, 1),
            font_name=FONT_NAME,
        )
        self.add_widget(self.console_text)

        # Input field and send button
        mid_row_y = 0.15
        self.input_field = RoundedTextInput(
            write_tab=False,
            multiline=False,
            hint_text='Input',
            size_hint=(0.9, 0.1),
            pos_hint={'x': 0, 'y': mid_row_y},
            font_size=28,
            font_name=FONT_NAME,
            padding_y=[14, 0]
        )
        self.input_field.bind(on_text_validate=self.on_enter)
        self.send_button = Button(
            background_normal='button_normal.png',
            background_down='button_down.png',
            on_press=self.on_enter,
            size_hint=(0.1, 0.1),
            pos_hint={'x': 0.9, 'y': mid_row_y}
        )
        self.send_label = Label(
            text='Send',
            color=(1, 1, 1, 1),
            size_hint=(0.1, 0.1),
            pos_hint={'x': 0.9, 'y': mid_row_y},
            font_size=25,
            font_name=FONT_NAME
        )
        self.add_widget(self.input_field)
        self.add_widget(self.send_button)
        self.add_widget(self.send_label)

        # Bottom controls: rewind, restart and counter
        bttm_row_y = 0.025
        self.rewind_button = Button(
            background_normal='button_normal.png',
            background_down='button_down.png',
            on_press=self.rewind,
            size_hint=(0.225, 0.1),
            pos_hint={'x': 0.1, 'y': bttm_row_y}
        )
        self.rewind_label = Label(
            text='Rewind',
            color=(1, 1, 1, 1),
            size_hint=(0.225, 0.1),
            pos_hint={'x': 0.1, 'y': bttm_row_y},
            font_size=25,
            font_name=FONT_NAME
        )
        self.restart_button = Button(
            background_normal='button_normal.png',
            background_down='button_down.png',
            on_press=self.restart,
            size_hint=(0.225, 0.1),
            pos_hint={'x': 0.4, 'y': bttm_row_y}
        )
        self.restart_label = Label(
            text='Restart',
            color=(1, 1, 1, 1),
            size_hint=(0.226, 0.1),
            pos_hint={'x': 0.4, 'y': bttm_row_y},
            font_size=25,
            font_name=FONT_NAME
        )
        self.counter_label = Label(
            text='Rewinds: ',
            size_hint=(0.1, 0.1),
            pos_hint={'x': 0.8, 'y': bttm_row_y},
            font_size=30,
            font_name=FONT_NAME
        )
        self.counter = Label(
            text='1',
            size_hint=(0.1, 0.1),
            pos_hint={'x': 0.9, 'y': bttm_row_y},
            font_size=30,
            font_name=FONT_NAME
        )
        self.add_widget(self.rewind_button)
        self.add_widget(self.rewind_label)
        self.add_widget(self.restart_button)
        self.add_widget(self.restart_label)
        self.add_widget(self.counter_label)
        self.add_widget(self.counter)

        # Loading text overlay
        self.loading_text = Label(
            text='',
            size_hint=(0.1, 0.1),
            pos_hint={'x': 0.45, 'y': 0.50},
            font_size=50,
            font_name=FONT_NAME
        )
        self.add_widget(self.loading_text)
        with self.loading_text.canvas.before:
            self.loading_color = Color(0, 0, 0, 0.8)
            self.loading_rect = Rectangle(size=self.loading_text.size, pos=self.loading_text.pos)
        self.loading_text.bind(size=self._update_loading_rect, pos=self._update_loading_rect)

        Clock.schedule_once(lambda dt: self.initialize_game(), 1)

    def _update_rect(self, instance, value):
        self.rect.pos = instance.pos
        self.rect.size = instance.size

    def _update_loading_rect(self, instance, value):
        self.loading_rect.pos = instance.pos
        self.loading_rect.size = instance.size
        self.loading_color.a = 0.8 if self.loading_text.text else 0

    def show_loading(self):
        self.loading_text.text = 'Loading...'
        self.loading_text.opacity = 1
        self.loading_color.a = 0.8
        self.loading_rect.size = (self.loading_text.size[0] * 2.55, self.loading_text.size[1])
        self.loading_rect.pos = (
            self.loading_text.pos[0] - self.loading_text.size[0] / 1.3,
            self.loading_text.pos[1]
        )

    def hide_loading(self):
        self.loading_text.text = ''
        self.loading_text.opacity = 0
        self.loading_color.a = 0.0

    def on_enter(self, instance):
        if self.game_over:
            return
        text = self.input_field.text
        self.console_text.text += '> ' + text + '\n\n'
        self.conversation.append({'role': 'user', 'content': text})
        self.show_loading()
        threading.Thread(target=self.generate_response_thread, args=(self.conversation,)).start()

    def generate_response_thread(self, conversation):
        response = generate_response(conversation)
        Clock.schedule_once(lambda dt: self.hide_loading(), 0)
        Clock.schedule_once(lambda dt: self.append_console_text(response + '\n'), 0)
        self.conversation.append({'role': 'assistant', 'content': response})
        if check_success(self.conversation):
            Clock.schedule_once(lambda dt: self.append_console_text(
                'Game Over. You have succeeded! Restart for a new game.\n'), 0)
            Clock.schedule_once(lambda dt: self.update_counter(str(int(self.counter.text) + 1)), 0)
            self.game_over = True
        if check_failure(self.conversation):
            Clock.schedule_once(lambda dt: self.append_console_text(
                'Game Over. You have failed and disappointed everyone. Restart for a new game.\n'), 0)
            self.game_over = True
        Clock.schedule_once(lambda dt: self.update_input_field(''), 0)
        Clock.schedule_once(lambda dt: setattr(self.input_field, 'focus', True), 0)
        self.console_text.cursor = (0, len(self.console_text.text))

    def rewind(self, instance):
        if len(self.conversation) >= 2:
            # Remove last user and assistant messages
            self.conversation.pop()
            self.conversation.pop()
            self.console_text.text = ''
            for message in self.conversation:
                if message['role'] == 'user':
                    self.console_text.text += '> ' + message['content'] + '\n\n'
                else:
                    self.console_text.text += message['content'] + '\n'

    def restart(self, instance):
        self.initialize_game()

    def update_console_text(self, text):
        self.console_text.text = text

    def append_console_text(self, text):
        self.console_text.text += text

    def update_counter(self, text):
        self.counter.text = text

    def update_input_field(self, text):
        self.input_field.text = text

    def initialize_game(self):
        self.show_loading()
        threading.Thread(target=self.initialize_game_thread).start()

    def initialize_game_thread(self):
        text = generate_prompt() + '\n'
        Clock.schedule_once(lambda dt: self.update_console_text(text), 0)
        Clock.schedule_once(lambda dt: self.hide_loading(), 0)
        self.conversation = [{'role': 'assistant', 'content': text}]
        self.game_over = False
        self.console_text.cursor = (0, 0)


class AdventureApp(App):
    def build(self):
        return Console()


if __name__ == '__main__':
    AdventureApp().run()
