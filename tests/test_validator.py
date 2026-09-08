from __future__ import annotations

import re
import unittest
from pathlib import Path

from rag_app.core import load_samples, project_root
from rag_app.validator import assemble_document, fixed_rules, validate_document


ENGLISH = (
    "Use @人物参考图 as the only subject and exact wig reference inside @背景参考图. "
    "Vertical 9:16, 30fps, 4K detail, realistic smartphone footage, one continuous half-body take, natural ambience, no dialogue. "
    "0-3 seconds: she stands centered and calmly presents the front hairline and full curl silhouette while the background stays fixed. "
    "3-10 seconds: she turns one shoulder, gently lifts the ends once, releases the curls so they settle naturally under gravity, then looks at the camera with a relaxed smile."
)
CHINESE = (
    "使用 @人物参考图 作为唯一人物和假发依据，并置于固定的 @背景参考图 中。9:16 竖屏、30fps、4K 细节、真实智能手机拍摄、一镜到底、半身构图、自然环境声、无对白。"
    "0-3 秒：她保持居中并自然展示正面发际线和完整卷发轮廓，背景保持不变。3-10 秒：她轻微转动一侧肩膀，只托起一次发尾，松手后让卷发在重力作用下自然恢复，最后看向镜头并放松微笑。"
)


class ValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = assemble_document(
            {"creative_type": "indoor", "duration": 10},
            {"positive_en": ENGLISH, "positive_zh": CHINESE},
        )

    def test_assembled_document_passes(self) -> None:
        report = validate_document(self.document, 10)
        self.assertTrue(report["valid"], report["errors"])

    def test_modified_negative_prompt_fails(self) -> None:
        modified = self.document.replace("Do not add any other people to the background.\n", "", 1)
        report = validate_document(modified, 10)
        self.assertFalse(report["valid"])
        self.assertTrue(any("英文负面提示词" in error for error in report["errors"]))

    def test_timeline_gap_fails(self) -> None:
        modified = self.document.replace("3-10 seconds", "4-10 seconds")
        report = validate_document(modified, 10)
        self.assertFalse(report["valid"])
        self.assertTrue(any("时间轴" in error for error in report["errors"]))

    def test_forbidden_sales_claim_fails(self) -> None:
        modified = self.document.replace("one continuous half-body take", "discount offer, one continuous half-body take")
        report = validate_document(modified, 10)
        self.assertFalse(report["valid"])
        self.assertTrue(any("discount" in error for error in report["errors"]))

    def test_outdoor_requires_one_continuous_take(self) -> None:
        document = assemble_document(
            {"creative_type": "outdoor", "duration": 10},
            {"positive_en": ENGLISH.replace("one continuous half-body take", "a stable half-body shot"), "positive_zh": CHINESE},
        )
        report = validate_document(document, 10)
        self.assertFalse(report["valid"])
        self.assertTrue(any("一镜到底" in error for error in report["errors"]))

    def test_rule_files_match_prd_code_blocks(self) -> None:
        prd = (project_root() / "PRD.md").read_text(encoding="utf-8")
        en_match = re.search(r"### 12\.1 英文执行版\s+```text\s+(.*?)\s+```", prd, re.DOTALL)
        zh_match = re.search(r"### 12\.2 中文审核版\s+```text\s+(.*?)\s+```", prd, re.DOTALL)
        self.assertIsNotNone(en_match)
        self.assertIsNotNone(zh_match)
        english, chinese = fixed_rules()
        self.assertEqual(english, en_match.group(1).strip())
        self.assertEqual(chinese, zh_match.group(1).strip())

    def test_every_approved_seed_can_be_assembled_and_validated(self) -> None:
        for sample in load_samples(approved_only=True):
            with self.subTest(sample=sample.id):
                document = assemble_document(
                    {"creative_type": sample.creative_type, "duration": sample.duration},
                    {"positive_en": sample.positive_en, "positive_zh": sample.positive_zh},
                )
                report = validate_document(document, sample.duration)
                self.assertTrue(report["valid"], report["errors"])



if __name__ == "__main__":
    unittest.main()
