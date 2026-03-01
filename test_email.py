from dotenv import load_dotenv
load_dotenv()
from emailer import send_digest

waiver = """## Daily Fantasy Hoops Digest: March 1st, 2026

**Overall Sentiment Summary:**
The fantasy playoffs are here, and the landscape is a minefield of injuries and "silly season" breakouts.

---

### **1. Top Waiver Wire Adds**

*   **Gui Santos (GSW)**: Averaging 15.2 points, 5.9 rebounds, 4.2 assists, 1.9 treys, 1.7 steals, and 0.8 blocks over his last nine starts. Must-add.
*   **Ryan Nembhard (DAL)**: Dallas waived Tyus Jones, elevating Nembhard. 9.9 pts, 6.1 ast in 17 starts. **4-game week.**
*   **Daniel Gafford (DAL)**: Off injury report, could see 30+ mins with Bagley out. 1.4 blk in last 10. **4-game week.**

---

### **2. Injury & News Alerts**

*   **Joel Embiid (PHI)**: Strained oblique, out at least 3 games.
*   **Jabari Smith Jr. (HOU)**: Tweaked ankle again, out at least 2 more games.
*   **Ty Jerome (MEM)**: Doubtful for Sunday, missing all back-to-backs.
*   **Alex Sarr (WAS)**: Shutdown candidate, season likely over.
"""

roster = """### 1. Roster Alerts

*   **Jabari Smith Jr. (Ankle):** Re-aggravated. **Drop unless you have IR.**
*   **Ty Jerome (Thigh):** Missing B2Bs throughout playoffs. **Drop immediately.**
*   **Alex Sarr:** Shutdown candidate. **Drop immediately.**

---

### 2. Suggested Add/Drops

**Drop:** Alex Sarr, Ty Jerome, Jabari Smith Jr.

**Add:** Gui Santos, Ryan Nembhard, Daniel Gafford
"""

send_digest(waiver, roster)
