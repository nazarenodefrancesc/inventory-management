"""
Tests for the restock order creation endpoint (POST /api/restock-orders).
"""
import pytest


class TestRestockOrderEndpoint:
    """Test suite for the POST /api/restock-orders endpoint."""

    def test_create_restock_order_happy_path(self, client):
        """Test creating a restock order returns a Submitted order."""
        payload = {
            "items": [
                {"sku": "PCB-001", "name": "Single Layer PCB Assembly",
                 "quantity": 100, "unit_price": 24.99, "trend": "increasing"}
            ]
        }
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        # Required Order fields are present
        for field in ("id", "order_number", "customer", "items", "status",
                      "order_date", "expected_delivery", "total_value"):
            assert field in order

        assert order["status"] == "Submitted"
        assert order["customer"] == "Internal Restocking"
        assert order["order_number"].startswith("ORD-RESTOCK-")
        assert len(order["items"]) == 1
        assert order["items"][0]["sku"] == "PCB-001"

    def test_total_value_matches_line_items(self, client):
        """Test total_value equals the sum of quantity * unit_price."""
        payload = {
            "items": [
                {"sku": "PCB-001", "name": "Single Layer PCB Assembly",
                 "quantity": 10, "unit_price": 24.99, "trend": "increasing"},
                {"sku": "TMP-201", "name": "Temperature Sensor Module",
                 "quantity": 5, "unit_price": 89.50, "trend": "stable"},
            ]
        }
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        expected_total = 10 * 24.99 + 5 * 89.50
        assert abs(order["total_value"] - expected_total) < 0.01

    def test_lead_time_uses_slowest_item_trend(self, client):
        """Expected delivery should reflect the max trend-based lead time.

        With a decreasing-trend item (21 days) mixed with faster trends, the
        order's lead time must be ~21 days (the slowest item).
        """
        payload = {
            "items": [
                {"sku": "AAA-001", "name": "Fast Item",
                 "quantity": 1, "unit_price": 10.0, "trend": "increasing"},
                {"sku": "BBB-002", "name": "Slow Item",
                 "quantity": 1, "unit_price": 10.0, "trend": "decreasing"},
            ]
        }
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        from datetime import datetime
        order_date = datetime.strptime(order["order_date"], "%Y-%m-%dT%H:%M:%S")
        expected = datetime.strptime(order["expected_delivery"], "%Y-%m-%dT%H:%M:%S")
        lead_days = (expected - order_date).days
        assert lead_days == 21

    def test_missing_trend_uses_default_lead_time(self, client):
        """An item with no/unknown trend should default to 14 days."""
        payload = {
            "items": [
                {"sku": "CCC-003", "name": "No Trend Item",
                 "quantity": 2, "unit_price": 5.0}
            ]
        }
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        from datetime import datetime
        order_date = datetime.strptime(order["order_date"], "%Y-%m-%dT%H:%M:%S")
        expected = datetime.strptime(order["expected_delivery"], "%Y-%m-%dT%H:%M:%S")
        assert (expected - order_date).days == 14

    def test_submitted_order_appears_in_orders_list(self, client):
        """A placed restock order should be retrievable via GET /api/orders?status=Submitted."""
        payload = {
            "items": [
                {"sku": "PCB-001", "name": "Single Layer PCB Assembly",
                 "quantity": 7, "unit_price": 24.99, "trend": "stable"}
            ]
        }
        create_response = client.post("/api/restock-orders", json=payload)
        assert create_response.status_code == 201
        created_number = create_response.json()["order_number"]

        list_response = client.get("/api/orders?status=Submitted")
        assert list_response.status_code == 200
        submitted = list_response.json()
        assert isinstance(submitted, list)
        assert any(o["order_number"] == created_number for o in submitted)
        # Every order returned under this filter must be Submitted
        for o in submitted:
            assert o["status"].lower() == "submitted"

    def test_empty_items_returns_400(self, client):
        """An empty items list is a bad request."""
        response = client.post("/api/restock-orders", json={"items": []})
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_missing_items_field_returns_422(self, client):
        """A payload missing the required items field fails validation."""
        response = client.post("/api/restock-orders", json={})
        assert response.status_code == 422
