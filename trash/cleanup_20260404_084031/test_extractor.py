#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import warnings


from extractors.people_extractor import PeopleExtractor
from extractors.keypoints_extractor import KeypointsExtractor
from extractors.decisions_extractor import DecisionsExtractor
from extractors.actions_extractor import ActionsExtractor
from extractors.summary_generator import SummaryGenerator


# =====================================================
# ★ 手動測資（純文字，不是 SRT）
# =====================================================
MANUAL_TEST_TEXT = """
于顥：先請大家上Slack看一下，就是我剛剛有丟，因為2-2、2-3剛剛只有口頭唸。我先把2-2、2-3的里程碑丟到Slack上面，請大家到OP-MSF那個頻道去看一下。我唸一下2-2、2-3的里程碑，第一個應該都是研議資料揭露的格式，無論是到時候在後台開表格，還是要提供什麼樣的格式，我們把那個格式討論出來，然後有一個月的研議時間，從明年的1月1日到1月底。第二個部分應該就是把這個格式建置出來之後，提供各委員還有各黨團可以去做自主的揭露，時間就是長期的，從這個資料格式建置出來後，2月1日開始一直到本屆結束。如果沒有問題的話，我們是不是照這樣子通過？謝謝。
接下來是3-2的部分，請阿Fi說明一下你們目前預擬的時程，待會再請公報處回應。謝謝。
曾柏瑜：我現在預擬的時程是現行公聽會的盤點、人力及成本評估報告，希望可以在明年1月底時先來做這樣子的評估。在評估完成之後，我們就來詳列工作計畫，有關詳列工作計畫，我剛剛想了一下，因為剛剛有提到相關成本不一定全部由立法院這邊支應，畢竟是委員自己所開的公聽會，是不是委員也要負擔部分。所以我在想，這部分是不是請黨團，還有資訊處，因為畢竟這些公聽會的資料，如果被翔實記錄下來要放在哪裡及如何發布，這可能要請資訊處一起來討論。有關工作計畫的詳列，我預定從2月到6月30日，目前是這樣子訂定，不知道大家有什麼想法？
其實我們在討論時，有討論到一個方式，假設最後根據人力及成本評估報告，還有盤點完所有立法委員各自舉辦的公聽會，發現這個東西真的沒有辦法由公報處或立院這邊用增加預算或增加人力的方式來處理，或許就提供一個格式告訴所有委員，如果你要辦公聽會，你需要填哪一些資料等，以及找哪些人來做記錄、這些人你可以去那邊找、有沒有哪些服務可以使用？這樣或許就不需要公報處來負擔所有的人力及成本。我們現在是用這樣的一個方法，才會希望在第二部分詳列工作計畫時，也將資訊處一起納進來討論。
主席（洪顧問慈庸）：我可不可以把時程部分再往後調一下？因為現在開始到1月可能都在處理預算，各個行政單位都非常的忙，所以我們是不是可以把盤點跟寫評估報告的部分移到明年6月30日，即評估的部分在上半年把它做出來？然後是第二個里程碑，阿Fi的意思是要跟黨團去討論嗎？
曾柏瑜：因為如果我們希望這些公開的部分是由立法委員各自承擔部分成本，就是剛剛大家在討論的，假設不是全部由公報處這邊負責，而是由各個委員來承擔的話，可能要跟黨團討論一下，就是會有這樣的可能性，所以我們才會把黨團也一起列到主責單位裡面，但wording或許也可以調整成黨團不一定是主責單位，而是找各黨團來討論，我不確定這個wording要怎麼firm會比較好。
主席（洪顧問慈庸）：請處長發言。
"""


# =====================================================
# 將純文字轉為 segments
# =====================================================
def text_to_segments(text: str, max_chars: int = 400):
    segments = []
    buffer = ""

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # 如果加上這一行會超過上限 → 先存一段
        if len(buffer) + len(line) + 1 > max_chars:
            segments.append({"text": buffer.strip()})
            buffer = line
        else:
            buffer += " " + line if buffer else line

    # 最後剩下的內容
    if buffer:
        segments.append({"text": buffer.strip()})

    return segments
def normalize_actions_brackets(raw_output: str) -> str:
    # 只做格式清理：去掉中括號
    return raw_output.replace("[", "").replace("]", "")

# =====================================================
# 單一 extractor 測試工具（最原始版本）
# =====================================================
def test_one(name, func):
    print(f"\n===== Testing {name} =====")
    try:
        result = func()
    except Exception as e:
        warnings.warn(f"{name} raised exception: {repr(e)}")
        print(f"❌ {name} exception: {repr(e)}")
        return ""

    # 型別檢查：不是 str 也不炸，轉成 str 並警告
    if not isinstance(result, str):
        warnings.warn(f"{name} output is {type(result).__name__}, auto-cast to str")
        result = "" if result is None else str(result)

    print(result)

    # 空字串：不 assert，中止會讓 pipeline 跑不下去；改成 warn
    if len(result.strip()) == 0:
        warnings.warn(f"{name} returned empty output (continue)")
        print(f"⚠️  {name} empty output (continue)")
    else:
        print(f"✓ {name} OK (len={len(result.strip())})")

    return result


    




# =====================================================
# main
# =====================================================
def main():
    print("🧪 使用【純文字輸入】測試")

    segments = text_to_segments(MANUAL_TEST_TEXT)


    if not segments:
        raise RuntimeError("❌ 沒有任何 segments")

    print(f"📦 segments 數量: {len(segments)}")

    # 初始化 Extractors（原本的樣子）
    people = PeopleExtractor()
    keypoints = KeypointsExtractor()
    decisions = DecisionsExtractor()
    actions = ActionsExtractor()
    summary = SummaryGenerator()

    # 逐一測試
    test_one("PeopleExtractor", lambda: people.extract(segments))
    test_one("KeypointsExtractor", lambda: keypoints.extract(segments))
    test_one("DecisionsExtractor", lambda: decisions.extract(segments))
    test_one("ActionsExtractor", lambda: normalize_actions_brackets(actions.extract(segments)))


    # Summary（如果你要）
    test_one(
        "SummaryGenerator",
        lambda: summary.generate(
            segments,
            people.extract(segments),
            keypoints.extract(segments),
            decisions.extract(segments),
            actions.extract(segments),
        ),    )


if __name__ == "__main__":
    main()
