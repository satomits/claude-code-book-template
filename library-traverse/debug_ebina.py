"""海老名市立図書館 - main.py と同じ呼び出し方でテスト"""
import traceback
import anyio
from src.library_traverse.libraries.ebina import EbinaLibrary

CARD = "102193638"
PWD = "Tk4dakb$"


async def test():
    scraper = EbinaLibrary(CARD, PWD)
    try:
        async with scraper:
            print("__aenter__ OK")
            logged_in = await scraper.login()
            print(f"login: {logged_in}")
            if not logged_in:
                print("Login failed")
                return
            loans = await scraper.get_loans()
            print(f"loans ({len(loans)}):")
            for loan in loans:
                print(f"  {loan}")
            reservations = await scraper.get_reservations()
            print(f"reservations ({len(reservations)}):")
            for rsv in reservations:
                print(f"  {rsv}")
            await scraper.logout()
            print("logout OK")
    except Exception:
        traceback.print_exc()


anyio.run(test)
