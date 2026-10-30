#!/usr/bin/env python3
"""Suggest calendar modes for an explicit local date; never schedule or draw cards."""
import argparse
import json
from datetime import date, timedelta

HOLIDAY_SOURCE = 'https://www.beijing.gov.cn/zhengce/zhengcefagui/202511/t20251104_4258873.html'
HOLIDAYS = {
    2026: [('元旦', '01-01', '01-03'), ('春节', '02-15', '02-23'),
           ('清明', '04-04', '04-06'), ('劳动节', '05-01', '05-05'),
           ('端午', '06-19', '06-21'), ('中秋', '09-25', '09-27'),
           ('国庆', '10-01', '10-07')]
}
MAKEUP = {2026: ['01-04', '02-14', '02-28', '05-09', '09-20', '10-10']}
QIXI = {2026: '08-19', 2027: '08-08'}


def context(today, region):
    events = []
    coverage_years = range(today.year, (today + timedelta(days=14)).year + 1)

    def add(mode, name, start, end=None, lead=7, source=None, **extra):
        end = end or start
        if start - timedelta(days=lead) <= today <= end:
            events.append(dict(mode=mode, event=name, start=start.isoformat(),
                               end=end.isoformat(), days_until=(start-today).days,
                               source=source, **extra))

    for year in range(today.year - 1, today.year + 2):
        for month, day, name, mode in [(2, 14, '情人节', '节日恋爱'),
                                      (5, 20, '520话题日', '节日恋爱'),
                                      (11, 11, '单身与自我陪伴话题日', '单身与自我陪伴')]:
            add(mode, name, date(year, month, day))
        if year in QIXI:
            add('节日恋爱', '七夕', date.fromisoformat(f'{year}-{QIXI[year]}'),
                source=f'https://www.hko.gov.hk/tc/gts/time/calendar/text/files/T{year}c.txt')
        add('年末／新年', '年末与新年整理', date(year, 12, 15), date(year+1, 1, 7), lead=0)
        if region == 'CN':
            for name, first, last in HOLIDAYS.get(year, []):
                start = date.fromisoformat(f'{year}-{first}')
                end = date.fromisoformat(f'{year}-{last}')
                add('假期安排', name, start, end, lead=14, source=HOLIDAY_SOURCE,
                    calendar_type='官方放假调休区间，非全部均为法定假日',
                    actual_schedule='尚需使用者确认实际休假')
                # Find the first official workday after the interval, including makeup days.
                work = end + timedelta(days=1)
                makeup = set(MAKEUP.get(year, []))
                while work.weekday() >= 5 and work.strftime('%m-%d') not in makeup:
                    work += timedelta(days=1)
                add('假后收心', name+'后收心', work, work+timedelta(days=3), lead=3,
                    source=HOLIDAY_SOURCE, actual_schedule='依个人实际复工日调整')
    month_end = (today.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
    if today.day <= 3 or today >= month_end-timedelta(days=2):
        add('月度整理', '月初／月末整理', today, lead=0)
    events.sort(key=lambda x: (abs(x['days_until']), x['mode'], x['event']))
    missing = []
    if region != 'CN':
        missing.append('需查证所在地官方假期；未使用中国大陆放假资料')
    else:
        missing.extend(f'{year}年官方放假调休需即时核实，勿沿用其他年份' for year in coverage_years if year not in HOLIDAYS)
    missing.extend(f'{year}年七夕未内建，若询问需查证农历对照表' for year in coverage_years if year not in QIXI)
    makeup_today = region == 'CN' and today.strftime('%m-%d') in MAKEUP.get(today.year, [])
    return dict(local_date=today.isoformat(), region=region, candidates=events,
                official_makeup_workday=makeup_today, verification_needed=missing,
                notice='候选话题，不代表通知已建立；没有候选不代表全年没有节日',
                fallback='没有相关节点时提供一般占卜或一周指引')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--date', required=True, help='User-local YYYY-MM-DD')
    p.add_argument('--region', default='CN', help='CN for mainland China; others require verification')
    args = p.parse_args()
    try:
        today = date.fromisoformat(args.date)
    except ValueError:
        p.error('date must be a valid ISO date, YYYY-MM-DD')
    print(json.dumps(context(today, args.region.upper()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
