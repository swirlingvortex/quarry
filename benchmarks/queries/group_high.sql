SELECT group_high, COUNT(*) AS n, SUM(units) AS units FROM sales GROUP BY group_high ORDER BY group_high;
