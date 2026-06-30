import sys, json, time
sys.path.insert(0, '.')

from parsers import _api_get, _html_get, _extract_next_data, _item_to_review

print("Тест 1: прямой API-запрос отзывов...")
t0 = time.time()
resp = _api_get("/reviews", params={
    "organizationAlias": "tinkoff",   # небольшой банк для быстрого теста
    "reviewObjectType": "bank",
    "pageSize": 5,
    "orderBy": "byDate",
})
print(f"  время: {time.time()-t0:.2f}с, статус: {resp.status_code if resp else 'None'}")
if resp:
    data = resp.json()
    print(f"  total: {data['total']}, pageSize: {data['pageSize']}, items: {len(data['items'])}")
    r = _item_to_review(data['items'][0], "tinkoff", "Тинькофф")
    print("\nПример отзыва:")
    for k, v in r.items():
        if k == 'body':
            print(f"  body: {repr(v[:80])}...")
        else:
            print(f"  {k}: {repr(v)}")

print("\nТест 2: список банков...")
t0 = time.time()
resp2 = _html_get('/banki/otzyvy/')
nd = _extract_next_data(resp2.text)
org_list = nd['props']['initialReduxState']['organizations']['organizationsList']
slugs = [o['alias'] for o in org_list if o.get('status') == 'active']
print(f"  время: {time.time()-t0:.2f}с, активных банков: {len(slugs)}")
print(f"  первые 5: {slugs[:5]}")
