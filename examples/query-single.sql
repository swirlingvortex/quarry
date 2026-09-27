-- Preserved single-table example from the M3 milestone.
SELECT region, COUNT(*) AS orders, SUM(amount) AS revenue
FROM sales
WHERE amount >= 50.0
GROUP BY region
ORDER BY revenue DESC NULLS LAST, region ASC NULLS LAST
LIMIT 10;
