from __future__ import annotations


def profile_metadata() -> dict:
    return {
        "profile_id": "opm_example",
        "display_name": "OPM Example Profile",
        "skill_name": "fr-nl-report-query",
        "report_names": {
            "future_flight_competition": "未来航班客座率票价分析",
            "airline_yoy": "航空集团经营提升分析",
        },
        "demo_queries": [
            "海口-北京首都的包干航线，近三天的票价和客座率与外航相比，有没有什么异常或者可以改进的吗",
            "这个月的各航司净利润的同比，谁表现得最差",
        ],
    }
