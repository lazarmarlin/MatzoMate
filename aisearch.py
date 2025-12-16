from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI()


def aiSearch(productName):
    response = client.responses.create(
        prompt={
            "id": "pmpt_6940379cd3c88196b79512be86e802d1070d1b26dad7e1e9",
            "version": "1",
        },
        input=f"{productName}",
    )
    return response.output_text
