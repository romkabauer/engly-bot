#%%
import logging
import typing
import ffprobe
import json
import random
import sys

from os import remove
from pydub import AudioSegment
from aiohttp import request

from aiogram import Bot, Dispatcher, executor, types, filters
from aiogram.types.message import ContentType
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils.callback_data import CallbackData
from aiogram.utils.exceptions import MessageNotModified
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext

from google.cloud import speech_v1 as speech

from config import TOKEN
from messages import MESSAGES, QUESTIONS
from utils import InterviewStates

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

bot = Bot(token=TOKEN)

dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

download_voices_path = '/Users/roman_bauer/Google Drive (pm.rvbauer@gmail.com)/TelegramBot_test/voices/ogg/'

def cancel_keyboard():
    return types.ReplyKeyboardMarkup().row(*(
            types.KeyboardButton('🙅 Cancel'),
        ))

def speech_to_text(config, audio):
    api_key_path = '/Users/roman_bauer/Google Drive (pm.rvbauer@gmail.com)/TelegramBot_test/english-telegram-bot-309908-da3ea19a17bf.json'
    client = speech.SpeechClient.from_service_account_json(api_key_path)
    response = client.recognize(config=config, audio=audio)
    return get_transcript(response)

def get_transcript(response):
    results = []
    for result in response.results:
        best_alternative = result.alternatives[0]
        results.append(best_alternative.transcript)
    return results

def convert_voice(download_voices_path, message):
    converted_path = '/Users/roman_bauer/Google Drive (pm.rvbauer@gmail.com)/TelegramBot_test/voices/flac/'
    
    ogg_voice = AudioSegment.from_ogg(download_voices_path + str(message.message_id) + '.ogg')
    ogg_voice.export(converted_path + str(message.message_id) + '.flac', format='flac')

    return converted_path + str(message.message_id) + '.flac'

async def check_answer(answer):
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'accept': 'application/json',
    }

    params = (
        ('text', answer),
        ('language', 'en-US'),
        ('enabledOnly', 'false'),
    )

    async with request('post', 'https://api.languagetoolplus.com/v2/check', params=params, headers=headers) as response:
        logger.debug('Checking results: %r', json.dumps(await response.json(), indent=4, sort_keys=True))
        return await response.json()

def format_errors_explanation(errors):
    if len(errors['matches']) == 0:
        message = 'Really nice! I want to highlight your brilliant English! No errors at all.'
    else:
        message = 'I have noticed following errors in your speech:\n\n'

        for ind, error in enumerate(errors['matches']):
            message += str(ind+1) + '. ' \
                + '*Error type:* ' + error['rule']['issueType']\
                + '. ' + error['message'] \
                + '\n*Original:* ' + error['sentence'] \
                + '\n*Advice:* Probably, you should use: ' \
                + ' / '.join(x['value'] for x in error['replacements']) \
                + '\n*Correct sentences:* ' \
                + error['context']['text'][:error['context']['offset']] \
                + error['replacements'][0]['value'] \
                + error['context']['text'][error['context']['offset'] + error['context']['length']:] \
                + '\n\n'
    return message

async def process_voice(message):
    logger.debug(message)
    await message.voice.download(download_voices_path + str(message.message_id) + '.ogg')
    converted_file_path = convert_voice(download_voices_path, message)
    
    config = dict(
        language_code="en-US",
        enable_automatic_punctuation=True,
    )
    with open(converted_file_path, 'rb') as f:
        audio = dict(content=f.read())
    
    remove(download_voices_path + str(message.message_id) + '.ogg')
    remove(converted_file_path)

    return speech_to_text(config, audio)[0]

@dp.message_handler(state='*', commands='start')
async def start_cmd_handler(message: types.Message, state: FSMContext):
    state.reset_state()
    await message.reply(f"Hi, {message.from_user.first_name}! " + MESSAGES['welcome_message'],
        reply_markup=types.ReplyKeyboardMarkup().row(*(
            types.KeyboardButton('😃 Yeah, great!'), 
            types.KeyboardButton('🤨 You? Teaching me? I\'d better die!')
        )),
        parse_mode='Markdown')

@dp.message_handler(commands='random')
async def random_cmd_handler(message: types.Message): 
    reply_message = f"*{random.choice(QUESTIONS)}*\n\nHere you go!\nYou can answer via text or voice message."
    await message.reply(reply_message, parse_mode='Markdown', reply=False)

@dp.message_handler(state='*', commands='interview')
async def interview_cmd_handler(message: types.Message, state: FSMContext):
    await InterviewStates.results.set()
    async with state.proxy() as data:
        data['results'] = [MESSAGES['interview_done']]
        await InterviewStates.question_number.set()
        data['question_number'] = 0
    await message.reply("Answer the question below or click 'Cancel' to finish interview immediately. \n\n*" + QUESTIONS[0] + "*",
        reply_markup=cancel_keyboard(),
        parse_mode='Markdown',
        reply=False)

@dp.message_handler(commands='list')
async def list_cmd_handler(message: types.Message):
    reply_message = "Let's pick a question you want to answer:"
    await message.reply(reply_message, reply_markup=types.ReplyKeyboardMarkup().row(*(
            types.KeyboardButton(x) for x in QUESTIONS
        ),
        types.KeyboardButton('🙅 Cancel')),
        reply=False
    )

@dp.message_handler(text='😃 Yeah, great!')
async def msg_handler(message: types.Message):
    logger.debug('The answer is %r', message.text)
    await message.reply(MESSAGES['agree_practice'], reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(text='🤨 You? Teaching me? I\'d better die!')
async def msg_handler(message: types.Message):
    logger.debug('The answer is %r', message.text)
    reply_text = "Oh no! Why?"
    await message.reply(reply_text, reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(text='🤨 You now... Fuck off, pal, I\'d handle it by myself.')
async def msg_handler(message: types.Message):
    logger.debug('The answer is %r', message.text)
    reply_text = "Good luck with your application, you dick🤪"
    await message.reply(reply_text, reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(state = InterviewStates.question_number)
async def interview_questions_handler(message: types.Message, state: FSMContext):
    if message.text == '🙅 Cancel':
        async with state.proxy() as data:
            data['results'].append(MESSAGES['canceled_interview'])
            await message.reply(text="".join(data['results']), 
                reply_markup=types.ReplyKeyboardRemove(),
                parse_mode='Markdown')
            await state.reset_state()
    else:
        current_state = await state.get_state()
        logger.debug(current_state)
        async with state.proxy() as data:
            data['results'].append("\n\n" + "*Question:* " + QUESTIONS[data['question_number']] + "\n" \
                + "*Your answer:* " + message.text + "\n" \
                + "*Result:* " + format_errors_explanation(await check_answer(message.text)))
            data['question_number'] += 1
            try:
                await message.reply(text=QUESTIONS[data['question_number']], 
                    reply_markup=cancel_keyboard(),reply=False)
            except IndexError:
                await message.reply("".join(data['results']), 
                    reply_markup=types.ReplyKeyboardRemove(),
                    parse_mode='Markdown')
                await state.reset_state()

@dp.message_handler()
async def all_msg_handler(message: types.Message):
    logger.debug('The answer is %r', message.text)

    if message.text in QUESTIONS:
        reply_message = f"*{message.text}*\n\nHere you go!" \
            + "\nYou can answer via text or voice message."
        await message.reply(reply_message, 
            parse_mode='Markdown', 
            reply_markup=types.ReplyKeyboardRemove())
    elif message.text == '🙅 Cancel':
        await message.reply(MESSAGES['agree_practice'],
            parse_mode='Markdown',
            reply_markup=types.ReplyKeyboardRemove()
        )
    else:
        await message.reply(format_errors_explanation(await check_answer(message.text)),
            parse_mode='Markdown',
            reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(state=InterviewStates.question_number, content_types=ContentType.VOICE)
async def interview_questions_handler(message: types.Message, state: FSMContext):
    text_from_voice = await process_voice(message)
    current_state = await state.get_state()
    logger.debug(current_state)
    async with state.proxy() as data:
        data['results'].append("\n\n" + "*Question:* " + QUESTIONS[data['question_number']] + "\n" \
            + "*Your answer:* " + text_from_voice + "\n" \
            + "*Result:* " + format_errors_explanation(await check_answer(text_from_voice)))
        data['question_number'] += 1
        try:
            await message.reply(text=QUESTIONS[data['question_number']], 
                reply_markup=cancel_keyboard(), reply=False)
        except IndexError:
            await message.reply(text="".join(data['results']), 
                reply_markup=types.ReplyKeyboardRemove(),
                parse_mode='Markdown')

@dp.message_handler(content_types=ContentType.VOICE)
async def voices_handler(message: types.Message):
    text_from_voice = await process_voice(message)
    await message.reply('If I understood you correctly, you said:\n\n' + text_from_voice)
    logger.debug('Checking results: %r', await check_answer(text_from_voice))
    await message.reply(format_errors_explanation(await check_answer(text_from_voice)), 
        parse_mode='Markdown',
        reply_markup=types.ReplyKeyboardRemove())

async def main():
    try:
        await dp.start_polling()
    finally:
        await bot.close()

await main()