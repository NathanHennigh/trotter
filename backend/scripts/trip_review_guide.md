# Trip Review Guide

This is the kind of feedback that will help improve Trotter's trip builder most:

1. **What was the real trip?**
   - Example: "This should be Singapore, not Narita. Narita was only a layover."

2. **Which places were only connections or technical stops?**
   - Example: "LFW was a refuel stop on the way to Addis Ababa; I did not visit Togo."

3. **Which legs belong together or should be split apart?**
   - Example: "Trips 72 and 73 are one Orlando trip."
   - Example: "This cluster should split before segment 188; that was a separate later trip."

4. **Which segments are wrong, duplicate, or impossible?**
   - Example: "ENV -> AIR is fake; I have never been to Brazil."

5. **Which legs are missing?**
   - Example: "There should be an outbound leg before the Ethiopia segment."

6. **What would you call the trip if you were naming it yourself?**
   - This is especially useful for multi-country trips, layovers, and open-jaw itineraries.

You do **not** need to review every trip. The best use of your time is reviewing trips that look suspicious, repeated, mislabeled, or incomplete.

Run the review UI:

```powershell
cd C:\Users\natha\projects\trotter\backend
python scripts\trip_review_server.py
```

It saves your answers to:

- `backend/scripts/trip_review_feedback.json`
- optionally `backend/scripts/trip_review_feedback.md` when you click **Export markdown**
