import logging
import typing
import json
import random
import sys

from os import remove, environ
from pydub import AudioSegment
from aiohttp import request
import aiohttp

from aiogram import Bot, Dispatcher, executor, types, filters
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types.message import ContentType
from aiogram.utils.callback_data import CallbackData
from aiogram.utils.exceptions import MessageNotModified
from aiogram.dispatcher import FSMContext
from asyncio import AbstractEventLoop
import asyncio

from google.cloud import speech_v1 as speech

from messages import MESSAGES, QUESTIONS
from utils import InterviewStates

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

loop: AbstractEventLoop = asyncio.new_event_loop()
asyncio.set_event_loop(loop=loop)

bot = Bot(token=environ("BOT_TOKEN"), loop=loop)

dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

session: aiohttp.ClientSession = aiohttp.ClientSession()

download_voices_path = '/home/app/voices/ogg/'
converted_path = '/home/app/voices/flac/'
api_key_path = '/home/app/google_sr_token.json'

def cancel_keyboard():
    return types.ReplyKeyboardMarkup().row(*(
            types.KeyboardButton('🙅 Cancel'),
        ))

def list_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for q in QUESTIONS:
        keyboard.row(*(
                types.KeyboardButton(q),
                ))
    keyboard.row(*(
            types.KeyboardButton('🙅 Cancel'),
        ))
    return keyboard

def speech_to_text(config, audio):
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
        return MESSAGES['no_errors']
    else:
        message = ''
        if errors['language']['code'] != errors['language']['detectedLanguage']['code']:
            message += f"Are you sure, it's in English? I guess it's {errors['language']['detectedLanguage']['name']} with " \
                + f"{errors['language']['detectedLanguage']['confidence']}% confidence.\n" \
                + "Anyway, if it is English, "
        message += 'I have noticed following errors in your speech:\n\n'

        for ind, error in enumerate(errors['matches']):
            message += str(ind+1) + '. ' \
                + '*Error type:* ' + error['rule']['issueType']\
                + '. ' + error['message']
            if len(error['replacements']) == 0:
                return message
            else:
                message += '\n*Original:* ' + error['sentence'] \
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

    try:
        return speech_to_text(config, audio)[0]
    except IndexError:
        return None

@dp.message_handler(state='*', commands='start')
async def start_cmd_handler(message: types.Message, state: FSMContext):
    state.reset_state()
    logger.debug(message)
    await message.reply(f"Hi, {message.from_user.first_name}! " + MESSAGES['welcome_message'],
        reply_markup=types.ReplyKeyboardMarkup().row(*(
            types.KeyboardButton('😃 Yeah, great!'), 
            types.KeyboardButton('🤨 You? Teaching me? I\'d better die!')
        )),
        parse_mode='Markdown')

@dp.message_handler(commands='random')
async def random_cmd_handler(message: types.Message): 
    logger.debug(message)
    reply_message = f"*{random.choice(QUESTIONS)}*" + MESSAGES['exercise']
    await message.reply(reply_message, parse_mode='Markdown', reply=False)

@dp.message_handler(state='*', commands='interview')
async def interview_cmd_handler(message: types.Message, state: FSMContext):
    logger.debug(message)
    await InterviewStates.results.set()
    async with state.proxy() as data:
        data['results'] = [MESSAGES['interview_done']]
        await InterviewStates.question_number.set()
        data['question_number'] = 0
    await message.reply("Answer the question below via TEXT or VOICE" \
        +" or click 'Cancel' to finish interview immediately. \n\n*" \
        + QUESTIONS[0] + "*",
        reply_markup=cancel_keyboard(),
        parse_mode='Markdown',
        reply=False)

@dp.message_handler(commands='list')
async def list_cmd_handler(message: types.Message):
    logger.debug(message)
    reply_message = "Let's pick a question you want to answer:"
    await message.reply(reply_message, reply_markup=list_keyboard(),
        reply=False
    )

@dp.message_handler(text='😃 Yeah, great!')
async def msg_handler(message: types.Message):
    logger.debug(message)
    logger.debug('The answer is %r', message.text)
    await message.reply(MESSAGES['agree_practice'], reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(text='🤨 You? Teaching me? I\'d better die!')
async def msg_handler(message: types.Message):
    logger.debug(message)
    logger.debug('The answer is %r', message.text)
    reply_text = "Oh no! Why?"
    await message.reply(reply_text, reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(text='🤨 You now... Fuck off, pal, I\'d handle it by myself.')
async def msg_handler(message: types.Message):
    logger.debug(message)
    logger.debug('The answer is %r', message.text)
    reply_text = "Good luck with your application, you dick🤪"
    await message.reply(reply_text, reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(state = InterviewStates.question_number)
async def interview_questions_handler(message: types.Message, state: FSMContext):
    if message.text == '🙅 Cancel':
        logger.debug(message)
        async with state.proxy() as data:
            data['results'].append(MESSAGES['canceled_interview'])
            await message.reply(text="".join(data['results']), 
                reply_markup=types.ReplyKeyboardRemove(),
                parse_mode='Markdown')
            await state.reset_state()
    else:
        current_state = await state.get_state()
        logger.debug(message)
        logger.debug(current_state)
        async with state.proxy() as data:
            data['results'].append("\n\n" + "*Question:* " + QUESTIONS[data['question_number']] + "\n" \
                + "*Your answer:* " + message.text + "\n" \
                + "*Result:* " + format_errors_explanation(await check_answer(message.text)))
            data['question_number'] += 1
            try:
                await message.reply(text=QUESTIONS[data['question_number']]+ MESSAGES['exercise'], 
                    reply_markup=cancel_keyboard(),reply=False)
            except IndexError:
                data['results'].append(MESSAGES['next_step'])
                await message.reply("".join(data['results']), 
                    reply_markup=types.ReplyKeyboardRemove(),
                    parse_mode='Markdown')
                await state.reset_state()

@dp.message_handler()
async def all_msg_handler(message: types.Message):
    logger.debug(message)
    logger.debug('The answer is %r', message.text)

    if message.text in QUESTIONS:
        reply_message = f"*{message.text}*" + MESSAGES['exercise']
        await message.reply(reply_message, 
            parse_mode='Markdown', 
            reply_markup=types.ReplyKeyboardRemove(),
            reply=False)
    elif message.text == '🙅 Cancel':
        await message.reply(MESSAGES['next_step'],
            parse_mode='Markdown',
            reply_markup=types.ReplyKeyboardRemove()
        )
    else:
        await message.reply(format_errors_explanation(await check_answer(message.text)) \
            + MESSAGES['next_step'],
            parse_mode='Markdown',
            reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(state=InterviewStates.question_number, content_types=ContentType.VOICE)
async def interview_questions_handler(message: types.Message, state: FSMContext):
    text_from_voice = await process_voice(message)
    if text_from_voice == None:
        text_from_voice = "Sorry, can't recognize"
    current_state = await state.get_state()
    async with state.proxy() as data:
        data['results'].append("\n\n" + "*Question:* " + QUESTIONS[data['question_number']] + "\n" \
            + "*Your answer:* " + text_from_voice + "\n" \
            + "*Result:* " + format_errors_explanation(await check_answer(text_from_voice)))
        data['question_number'] += 1
        try:
            await message.reply(text=QUESTIONS[data['question_number']], 
                reply_markup=cancel_keyboard(), reply=False)
        except IndexError:
            data['results'].append(MESSAGES['next_step'])
            await message.reply(text="".join(data['results']), 
                reply_markup=types.ReplyKeyboardRemove(),
                parse_mode='Markdown')
            await state.reset_state()

@dp.message_handler(content_types=ContentType.VOICE)
async def voices_handler(message: types.Message):
    text_from_voice = await process_voice(message)
    if text_from_voice == None:
        text_from_voice = "Sorry, can't recognize"
        logger.debug(text_from_voice)
        await message.reply((text_from_voice), 
            parse_mode='Markdown',
            reply_markup=types.ReplyKeyboardRemove())
    else:
        await message.reply('If I understood you correctly, you said:\n\n' + text_from_voice)
        logger.debug('Checking results: %r', await check_answer(text_from_voice))
        await message.reply(format_errors_explanation(await check_answer(text_from_voice)), 
            parse_mode='Markdown',
            reply_markup=types.ReplyKeyboardRemove())

async def shutdown(dp):
    await dp.storage.close()
    await dp.storage.wait_closed()
    await session.close()

if __name__ == '__main__':
    print("start")
    executor.start_polling(dp, on_shutdown=shutdown, loop=loop)