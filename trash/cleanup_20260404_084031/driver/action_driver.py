# drivers/actions_driver.py
# -*- coding: utf-8 -*-

class ActionsExtractorDriver:
    def __init__(self, extractor, verbose=True):
        """
        extractor: ActionsExtractor instance
        """
        self.extractor = extractor
        self.verbose = verbose

    def run(self, segments):
        """
        統一驅動 ActionsExtractor.extract()

        回傳：
            {
                "ok": bool,
                "result": str,
                "error": Optional[str]
            }
        """
        if self.verbose:
            print("\n===== Running ActionsExtractor =====")

        try:
            result = self.extractor.extract(segments)

            # ===== 驗證輸出 =====
            if not isinstance(result, str):
                return {
                    "ok": False,
                    "result": "",
                    "error": f"Expected str, got {type(result)}"
                }

            if len(result.strip()) == 0:
                return {
                    "ok": False,
                    "result": "",
                    "error": "Empty result string"
                }

            if self.verbose:
                print("----- Extracted Actions -----")
                print(result)
                print("✓ ActionsExtractor OK")

            return {
                "ok": True,
                "result": result,
                "error": None
            }

        except Exception as e:
            return {
                "ok": False,
                "result": "",
                "error": str(e)
            }
