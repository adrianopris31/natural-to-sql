-- Create read-only user for natural-to-sql
-- For production / real DB: replace `ecommerce` with your database name
-- and `nl2sql_ro_pass` with a secure random password.

CREATE USER IF NOT EXISTS `nl2sql_ro`@'%' IDENTIFIED BY 'nl2sql_ro_pass';
GRANT SELECT ON `ecommerce`.* TO `nl2sql_ro`@'%';
FLUSH PRIVILEGES;
