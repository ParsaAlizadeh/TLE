import sys
import bs4
import requests
import json

session = requests.Session()

def query_page(url):
    with session.get(url) as resp:
        html_raw = resp.text
        soup = bs4.BeautifulSoup(html_raw, features="lxml")
        table = soup.find_all("table")[0]
        rows = table.find_all("tr")[1:]
        result = []
        for row in rows:
            span = row.find("span", {"class": "small"})
            if span is None:
                continue
            cnt = int(span.text.split('/')[0])
            col = row.find_all("td")[0]
            problem_id = col.text.strip()
            result.append([problem_id, cnt])
    return result

def page_counts(url):
    with session.get(url) as resp:
        html_raw = resp.text
        soup = bs4.BeautifulSoup(html_raw, features="lxml")
        page_div = soup.find_all("ul")[-1]
        page_num = page_div.find_all("span", {"class": "page-index"})[-1].text
        return int(page_num)
    return 0

def main():
    if len(sys.argv) < 3:
        print("Not enough arguments")
        return

    list_key = sys.argv[1]
    name = sys.argv[2]

    print('This will take a while')
    page_num = page_counts("https://codeforces.com/problemset/")

    print(f"{page_num} pages to check...")
    url = "https://codeforces.com/problemset/page/{}?list={}"
    counts = []
    for i in range(1, page_num + 1):
        current_page = url.format(i, list_key)
        print(f"Query page {i}:", current_page)
        result = query_page(current_page)
        counts += result

    print(f'Found result for {len(counts)} problems')

    counts = {p[0]: p[1] for p in counts}
    with open(f"{name}.json", "w") as file:
        json.dump(counts, file, indent=4)

    print(f"Move {name}.json into data/list/ directory")

    session.close()

if __name__ == "__main__":
    main()
