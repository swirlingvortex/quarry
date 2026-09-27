SELECT group_low, COUNT(*) AS n, SUM(units) AS units FROM sales GROUP BY group_low ORDER BY group_low;
