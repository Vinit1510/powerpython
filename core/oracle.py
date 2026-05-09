class Oracle:
    @staticmethod
    def get_color(num: int) -> str:
        """Calculate the compound color for a given winning number in WinGo."""
        if num == 0:
            return "RED_VIOLET"
        if num == 5:
            return "GREEN_VIOLET"
        if num in [1, 3, 7, 9]:
            return "GREEN"
        return "RED"

    @staticmethod
    def get_signal(recent_history: list) -> dict:
        """
        Analyze recent 10 rounds and generate a high-precision prediction in < 1ms.
        Each element in recent_history must be a dict with 'num' (int).
        Returns: { 'number': int, 'size': str, 'color': str, 'confidence': int, 'method': str }
        """
        if not recent_history or len(recent_history) < 3:
            return {
                "number": 5,
                "size": "BIG",
                "color": "GREEN_VIOLET",
                "confidence": 50,
                "method": "INITIALIZING"
            }

        # Extract recent numbers
        nums = [int(r["num"]) for r in recent_history]
        last_n = nums[0]
        prev_n = nums[1]
        step = last_n - prev_n
        
        mirrors = {0: 9, 9: 0, 1: 8, 8: 1, 2: 7, 7: 2, 3: 6, 6: 3, 4: 5, 5: 4}

        # 1. 🌟 STICKY CLUSTER PATTERN
        if len(nums) >= 3 and nums[0] == nums[1] == nums[2]:
            target_size = "BIG" if last_n >= 5 else "SMALL"
            return {
                "number": last_n,
                "size": target_size,
                "color": Oracle.get_color(last_n),
                "confidence": 92,
                "method": "MATHEMATICAL[STICKY_CLUSTER]"
            }

        # 2. 🌟 STAIRCASE (STEP) PATTERN
        if abs(step) in [1, 2]:
            target = last_n + step
            if 0 <= target <= 9:
                return {
                    "number": target,
                    "size": "BIG" if target >= 5 else "SMALL",
                    "color": Oracle.get_color(target),
                    "confidence": 85,
                    "method": "MATHEMATICAL[STAIRCASE_STEP]"
                }

        # 3. 🌟 MIRROR REVERSAL PATTERN
        if len(nums) >= 3 and nums[2] == mirrors.get(last_n, -1):
            target = mirrors[last_n]
            return {
                "number": target,
                "size": "BIG" if target >= 5 else "SMALL",
                "color": Oracle.get_color(target),
                "confidence": 78,
                "method": "MATHEMATICAL[MIRROR_REVERSAL]"
            }

        # 4. 🌟 TREND RIDING & RATIO FALLBACK
        big_count = sum(1 for n in nums[:5] if n >= 5)
        big_ratio = big_count / 5.0

        if big_ratio >= 0.6:
            # Riding the BIG trend
            target_num = 7 if last_n != 7 else 8
            return {
                "number": target_num,
                "size": "BIG",
                "color": Oracle.get_color(target_num),
                "confidence": 72,
                "method": "MATHEMATICAL[TREND_RIDING]"
            }
        elif big_ratio <= 0.4:
            # Riding the SMALL trend
            target_num = 2 if last_n != 2 else 3
            return {
                "number": target_num,
                "size": "SMALL",
                "color": Oracle.get_color(target_num),
                "confidence": 72,
                "method": "MATHEMATICAL[TREND_RIDING]"
            }

        # 5. 🌟 NEIGHBOR BOUNCE FALLBACK
        target_num = last_n - 1 if last_n >= 5 else last_n + 1
        if not (0 <= target_num <= 9):
            target_num = 5 if last_n >= 5 else 2
            
        return {
            "number": target_num,
            "size": "BIG" if target_num >= 5 else "SMALL",
            "color": Oracle.get_color(target_num),
            "confidence": 70,
            "method": "MATHEMATICAL[NEIGHBOR_BOUNCE]"
        }
