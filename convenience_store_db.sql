-- MySQL dump 10.13  Distrib 8.0.46, for Linux (x86_64)
--
-- Host: localhost    Database: convenience_store_db
-- ------------------------------------------------------
-- Server version	8.0.46-0ubuntu0.22.04.3

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `outbound_history`
--

DROP TABLE IF EXISTS `outbound_history`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `outbound_history` (
  `name` varchar(50) NOT NULL,
  `SN` varchar(50) NOT NULL,
  `outbound_date` date NOT NULL DEFAULT (curdate())
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `outbound_history`
--

LOCK TABLES `outbound_history` WRITE;
/*!40000 ALTER TABLE `outbound_history` DISABLE KEYS */;
INSERT INTO `outbound_history` VALUES ('choco','SN0002','2026-07-10'),('smoke','SN0017','2026-07-10'),('drink','SN0010','2026-07-10'),('coffee','SN0005','2026-07-12'),('coffee','SN0005','2026-07-12'),('drink','SN0011','2026-07-12'),('drink','SN0010','2026-07-12'),('cup_noodle','SN0008','2026-07-12'),('smoke','SN0016','2026-07-12'),('choco','SN0002','2026-07-12'),('cup_noodle','SN0008','2026-07-12'),('drink','SN0010','2026-07-12'),('coffee','SN0005','2026-07-12'),('drink','SN0011','2026-07-12'),('smoke','SN0016','2026-07-12'),('cup_noodle','SN0007','2026-07-12'),('jjolbyung','SN0013','2026-07-13'),('smoke','SN0016','2026-07-13'),('drink','SN0011','2026-07-13'),('choco','SN0002','2026-07-13'),('coffee','SN0004','2026-07-13'),('smoke','SN0016','2026-07-13'),('smoke','SN0016','2026-07-13');
/*!40000 ALTER TABLE `outbound_history` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `products`
--

DROP TABLE IF EXISTS `products`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `products` (
  `name` varchar(50) NOT NULL,
  `SN` varchar(50) NOT NULL,
  `price` int NOT NULL,
  `expiry_date` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`SN`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `products`
--

LOCK TABLES `products` WRITE;
/*!40000 ALTER TABLE `products` DISABLE KEYS */;
INSERT INTO `products` VALUES ('choco','SN0001',2500,'2027-06-20'),('coffee','SN0005',3000,'2027-07-21'),('cup_noodle','SN0007',2500,'2027-06-11'),('cup_noodle','SN0008',2500,'2027-06-21'),('drink','SN0010',2000,'2027-06-16'),('drink','SN0011',2000,'2027-06-21'),('jjolbyung','SN0014',2500,'2027-06-17'),('smoke','SN0016',4500,NULL),('smoke','SN0017',4500,NULL);
/*!40000 ALTER TABLE `products` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Temporary view structure for view `stock`
--

DROP TABLE IF EXISTS `stock`;
/*!50001 DROP VIEW IF EXISTS `stock`*/;
SET @saved_cs_client     = @@character_set_client;
/*!50503 SET character_set_client = utf8mb4 */;
/*!50001 CREATE VIEW `stock` AS SELECT 
 1 AS `name`,
 1 AS `stock`*/;
SET character_set_client = @saved_cs_client;

--
-- Final view structure for view `stock`
--

/*!50001 DROP VIEW IF EXISTS `stock`*/;
/*!50001 SET @saved_cs_client          = @@character_set_client */;
/*!50001 SET @saved_cs_results         = @@character_set_results */;
/*!50001 SET @saved_col_connection     = @@collation_connection */;
/*!50001 SET character_set_client      = utf8mb4 */;
/*!50001 SET character_set_results     = utf8mb4 */;
/*!50001 SET collation_connection      = utf8mb4_0900_ai_ci */;
/*!50001 CREATE ALGORITHM=UNDEFINED */
/*!50013 DEFINER=`root`@`localhost` SQL SECURITY DEFINER */
/*!50001 VIEW `stock` AS select `products`.`name` AS `name`,count(0) AS `stock` from `products` group by `products`.`name` */;
/*!50001 SET character_set_client      = @saved_cs_client */;
/*!50001 SET character_set_results     = @saved_cs_results */;
/*!50001 SET collation_connection      = @saved_col_connection */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-07-13 17:38:47
