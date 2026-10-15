#!/usr/bin/env python3
"""Обновляет data.json из официальной страницы РСТ Бурятии (тарифы для Улан-Удэ).

Запуск:
  python scripts/update_tariffs.py              # скачать страницу и обновить data.json
  python scripts/update_tariffs.py --dry-run    # только показать, что изменится
  python scripts/update_tariffs.py --file page.html   # разобрать сохранённую страницу

Коды выхода: 0 всё хорошо (в том числе «изменений нет»), 1 страница не скачалась,
2 страница изменилась и разобрать её не удалось, либо цифры выглядят неправдоподобно.
В этих случаях data.json не меняется, приложение продолжает показывать прежние данные.
"""
import argparse, datetime, html, json, os, re, sys, urllib.request

URL = 'https://egov-buryatia.ru/rst/activities/monitoring/tariffs.php'
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data.json')

# ключ, фраза-якорь в порядке появления на странице
ANCHORS = [
    ('cold', 'Холодное водоснабжение'),
    ('sewer', 'Водоотведение'),
    ('hotO', 'открытая система'),
    ('hotC', 'закрытая система'),
    ('heat', 'Отопление'),
    ('el', '1 диапазон'),
    ('tko', 'Обращение с ТКО'),
]
# допустимые границы текущих тарифов (защита от ошибок разбора)
RANGES = {'cold': (10, 400), 'sewer': (10, 400), 'hotO': (50, 900), 'hotC': (50, 900),
          'heat': (500, 12000), 'el': (1, 40), 'tko': (100, 4000)}


def fetch():
    req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0 (budget-updater)',
                                               'Accept-Language': 'ru'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode('utf-8', 'replace')


def to_text(raw):
    raw = re.sub(r'(?is)<(script|style).*?</\1>', ' ', raw)
    raw = re.sub(r'(?s)<[^>]+>', ' ', raw)
    return re.sub(r'\s+', ' ', html.unescape(raw)).strip()


def numbers(seg):
    return [float(x.replace(',', '.')) for x in re.findall(r'(?<![\d,])\d+,\d+(?!\d)', seg)]


def iso(d):
    return datetime.datetime.strptime(d, '%d.%m.%Y').strftime('%Y-%m-%d')


def parse(text):
    i = text.find('Тарифы на коммунальные услуги на')
    j = text.find('за все периоды')
    sec = text[i:j] if 0 <= i < j else text
    pos, at = [], 0
    for key, phrase in ANCHORS:
        p = sec.find(phrase, at)
        if p < 0:
            raise ValueError('на странице не найдена строка «%s»' % phrase)
        pos.append((key, p))
        at = p + len(phrase)
    header = sec[:pos[0][1]]
    dates = re.findall(r'с\s*(\d\d\.\d\d\.\d{4})\s*по\s*(\d\d\.\d\d\.\d{4})', header)
    if not dates:
        raise ValueError('не найдены даты периодов')
    periods = [{'from': iso(a), 'to': iso(b)} for a, b in dates[-2:]]
    tariffs = {}
    for n, (key, p) in enumerate(pos):
        end = pos[n + 1][1] if n + 1 < len(pos) else len(sec)
        seg = sec[p:end]
        if key == 'el' and '2 диапазон' in seg:
            seg = seg[:seg.find('2 диапазон')]
        vals = numbers(seg)
        if not vals:
            raise ValueError('нет значений для «%s»' % key)
        tariffs[key] = [vals[-2], vals[-1]] if len(vals) >= 2 else [None, vals[-1]]
    return periods, tariffs


def merge(old, periods, tariffs):
    """Если на странице пока один период, прежний текущий период становится предыдущим."""
    if len(periods) == 1 or any(v[0] is None for v in tariffs.values()):
        periods = [old['periods'][1], periods[-1]]
        for k, v in tariffs.items():
            if v[0] is None:
                v[0] = old['tariffs'][k][1]
    for k, (lo, hi) in RANGES.items():
        cur = tariffs[k][1]
        if not lo <= cur <= hi:
            raise ValueError('значение «%s»=%s вне допустимых границ' % (k, cur))
        was = old['tariffs'][k][1]
        if cur and was and not 0.5 <= cur / was <= 2:
            raise ValueError('«%s» изменился слишком сильно (%s → %s), проверьте вручную' % (k, was, cur))
    return periods, tariffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    try:
        raw = open(a.file, encoding='utf-8').read() if a.file else fetch()
    except Exception as e:
        print('Не удалось скачать страницу РСТ: %s' % e)
        return 1
    old = json.load(open(DATA, encoding='utf-8'))
    try:
        periods, tariffs = merge(old, *parse(to_text(raw)))
    except Exception as e:
        print('Страница РСТ изменилась или цифры неправдоподобны: %s' % e)
        return 2
    if periods == old['periods'] and tariffs == old['tariffs']:
        print('Тарифы не изменились.')
        return 0
    print('Тарифы изменились:')
    for k in tariffs:
        if tariffs[k] != old['tariffs'][k]:
            print('  %s: %s -> %s' % (k, old['tariffs'][k], tariffs[k]))
    if a.dry_run:
        return 0
    old['periods'], old['tariffs'] = periods, tariffs
    old['updated'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
    with open(DATA, 'w', encoding='utf-8') as f:
        json.dump(old, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('data.json обновлён.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
