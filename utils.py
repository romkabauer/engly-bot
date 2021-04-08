#%%
from aiogram.dispatcher.filters.state import State, StatesGroup

class InterviewStates(StatesGroup):
    question_number = State()
    results = State()

if __name__ == '__main__':
    print(InterviewStates)