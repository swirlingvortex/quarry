SELECT c.region, COUNT(*) AS n, SUM(s.units) AS units
FROM sales AS s INNER JOIN customers AS c ON s.customer_id = c.customer_id
WHERE s.bucket < 500 GROUP BY c.region ORDER BY 1 NULLS LAST;
