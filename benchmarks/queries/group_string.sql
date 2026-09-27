SELECT region, COUNT(*) AS n, SUM(amount) AS revenue FROM sales GROUP BY region ORDER BY region NULLS LAST;
