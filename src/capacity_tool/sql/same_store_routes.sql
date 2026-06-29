WITH
parameters AS (
  SELECT
    CAST(? AS VARCHAR) AS carrier_code,
    CAST(? AS DATE) AS current_start,
    CAST(? AS DATE) AS current_end,
    CAST(? AS DATE) AS prior_start,
    CAST(? AS DATE) AS prior_end
),
active_batch AS (
  SELECT source_batch_id
  FROM import_batch
  GROUP BY source_batch_id
  HAVING COUNT(DISTINCT report_type) = 2
  ORDER BY MAX(imported_at) DESC
  LIMIT 1
),
current_carrier AS (
  SELECT
    capacity.origin_code,
    capacity.destination_code,
    SUM(capacity.seats) AS carrier_seats_current
  FROM carrier_capacity AS capacity
  JOIN active_batch AS batch
    ON capacity.source_batch_id = batch.source_batch_id
  CROSS JOIN parameters
  WHERE capacity.carrier_code = parameters.carrier_code
    AND capacity.travel_month BETWEEN parameters.current_start
                                  AND parameters.current_end
  GROUP BY capacity.origin_code, capacity.destination_code
  HAVING SUM(capacity.seats) > 0
),
prior_carrier AS (
  SELECT
    capacity.origin_code,
    capacity.destination_code,
    SUM(capacity.seats) AS carrier_seats_prior
  FROM carrier_capacity AS capacity
  JOIN active_batch AS batch
    ON capacity.source_batch_id = batch.source_batch_id
  CROSS JOIN parameters
  WHERE capacity.carrier_code = parameters.carrier_code
    AND capacity.travel_month BETWEEN parameters.prior_start
                                  AND parameters.prior_end
  GROUP BY capacity.origin_code, capacity.destination_code
  HAVING SUM(capacity.seats) > 0
),
same_store_routes AS (
  SELECT
    current.origin_code,
    current.destination_code,
    current.carrier_seats_current,
    prior.carrier_seats_prior
  FROM current_carrier AS current
  INNER JOIN prior_carrier AS prior
    ON current.origin_code = prior.origin_code
   AND current.destination_code = prior.destination_code
),
current_market AS (
  SELECT
    routes.origin_code,
    routes.destination_code,
    SUM(market.seats) AS market_seats_current
  FROM same_store_routes AS routes
  INNER JOIN market_capacity AS market
    ON routes.origin_code = market.origin_code
   AND routes.destination_code = market.destination_code
  JOIN active_batch AS batch
    ON market.source_batch_id = batch.source_batch_id
  CROSS JOIN parameters
  WHERE market.travel_month BETWEEN parameters.current_start
                                AND parameters.current_end
  GROUP BY routes.origin_code, routes.destination_code
),
prior_market AS (
  SELECT
    routes.origin_code,
    routes.destination_code,
    SUM(market.seats) AS market_seats_prior
  FROM same_store_routes AS routes
  INNER JOIN market_capacity AS market
    ON routes.origin_code = market.origin_code
   AND routes.destination_code = market.destination_code
  JOIN active_batch AS batch
    ON market.source_batch_id = batch.source_batch_id
  CROSS JOIN parameters
  WHERE market.travel_month BETWEEN parameters.prior_start
                                AND parameters.prior_end
  GROUP BY routes.origin_code, routes.destination_code
)
SELECT
  routes.origin_code,
  routes.destination_code,
  routes.carrier_seats_current,
  routes.carrier_seats_prior,
  routes.carrier_seats_current
    - routes.carrier_seats_prior AS carrier_seat_change,
  CAST(
    routes.carrier_seats_current - routes.carrier_seats_prior
    AS DOUBLE
  ) / NULLIF(routes.carrier_seats_prior, 0) AS carrier_seat_change_pct,
  current_market.market_seats_current,
  prior_market.market_seats_prior,
  current_market.market_seats_current
    - routes.carrier_seats_current AS oa_seats_current,
  prior_market.market_seats_prior
    - routes.carrier_seats_prior AS oa_seats_prior,
  (
    current_market.market_seats_current - routes.carrier_seats_current
  ) - (
    prior_market.market_seats_prior - routes.carrier_seats_prior
  ) AS oa_seat_change,
  CAST(
    (
      current_market.market_seats_current - routes.carrier_seats_current
    ) - (
      prior_market.market_seats_prior - routes.carrier_seats_prior
    )
    AS DOUBLE
  ) / NULLIF(
    prior_market.market_seats_prior - routes.carrier_seats_prior,
    0
  ) AS oa_seat_change_pct
FROM same_store_routes AS routes
INNER JOIN current_market
  ON routes.origin_code = current_market.origin_code
 AND routes.destination_code = current_market.destination_code
INNER JOIN prior_market
  ON routes.origin_code = prior_market.origin_code
 AND routes.destination_code = prior_market.destination_code
