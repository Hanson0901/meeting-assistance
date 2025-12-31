import os
from datetime import datetime
from test_extractor import run_extractors_from_text
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


#INPUT_FILE = "input/meeting.txt"
#OUTPUT_DIR = "output"


def read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def generate_pdf(result: dict, output_path: str):
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4

    y = height - 40
    line_height = 16

    def draw_section(title, content):
        nonlocal y
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, y, title)
        y -= line_height * 1.5

        c.setFont("Helvetica", 11)
        for line in content.splitlines():
            if y < 40:
                c.showPage()
                y = height - 40
            c.drawString(50, y, line)
            y -= line_height
        y -= line_height

    draw_section("Summary", result["summary"])
    draw_section("People", result["people"])
    draw_section("Key Points", result["keypoints"])
    draw_section("Decisions", result["decisions"])
    draw_section("Actions", result["actions"])

    c.save()


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    text = read_text_file(INPUT_FILE)
    result = run_extractors_from_text(text)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"{OUTPUT_DIR}/report_{timestamp}.pdf"

    generate_pdf(result, output_file)

    print(f"✅ 分析完成，PDF 已產生：{output_file}")


if __name__ == "__main__":
    main()
