SELECT c.region, COUNT(*) AS orders, SUM(s.amount) AS revenue
FROM sales AS s
INNER JOIN customers AS c ON s.customer_id = c.customer_id
WHERE s.amount >= 50.0
GROUP BY c.region
ORDER BY revenue DESC NULLS LAST, region ASC
LIMIT 10;
