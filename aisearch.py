from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI()


def aiSearch(ingredientText):
    """
    Given a short/incomplete ingredient string or product name, returns:
      - A comma-separated list of flagged chametz ingredients, or
      - "kosher" if nothing is flagged, or
      - "unknown" if the product can't be identified
    """
    response = client.responses.create(
        prompt={
            "id": "pmpt_6940379cd3c88196b79512be86e802d1070d1b26dad7e1e9",
            "version": "1",
        },
        input=ingredientText,
    )
    return response.output_text.strip()
