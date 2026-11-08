"""Unit tests for I/O request models and request queue management (Incremento 1)."""

import unittest

from os_simulator.io.queue import IOQueue
from os_simulator.io.request import (
    IOOperationType,
    IOPriority,
    IORequest,
    IORequestStatus,
)


class TestIORequestAndQueue(unittest.TestCase):
    """Test suite for IORequest and IOQueue."""

    def test_create_read_request(self):
        req = IORequest(
            operation=IOOperationType.READ,
            block_id=10,
            track=2,
            priority=IOPriority.HIGH,
        )
        self.assertEqual(req.operation, IOOperationType.READ)
        self.assertEqual(req.block_id, 10)
        self.assertEqual(req.track, 2)
        self.assertEqual(req.priority, IOPriority.HIGH)
        self.assertEqual(req.status, IORequestStatus.PENDING)
        self.assertIsNone(req.data)

    def test_create_write_request(self):
        payload = b"Hello Storage"
        req = IORequest(
            operation=IOOperationType.WRITE,
            block_id=5,
            data=payload,
        )
        self.assertEqual(req.operation, IOOperationType.WRITE)
        self.assertEqual(req.block_id, 5)
        # Default sectors_per_track = 4 -> 5 // 4 = track 1
        self.assertEqual(req.track, 1)
        self.assertEqual(req.data, payload)

    def test_invalid_requests(self):
        # Negative block_id
        with self.assertRaises(ValueError):
            IORequest(operation=IOOperationType.READ, block_id=-1)

        # WRITE without data
        with self.assertRaises(ValueError):
            IORequest(operation=IOOperationType.WRITE, block_id=0, data=None)

    def test_status_transitions(self):
        req = IORequest(operation=IOOperationType.READ, block_id=1)
        self.assertEqual(req.status, IORequestStatus.PENDING)

        req.mark_processing()
        self.assertEqual(req.status, IORequestStatus.PROCESSING)

        req.mark_completed(result=b"data_out", seek_distance=15)
        self.assertEqual(req.status, IORequestStatus.COMPLETED)
        self.assertEqual(req.result, b"data_out")
        self.assertEqual(req.seek_distance, 15)
        self.assertIsNotNone(req.completed_at)

    def test_mark_failed(self):
        req = IORequest(operation=IOOperationType.READ, block_id=2)
        req.mark_failed("Erro de E/S: Bloco danificado")
        self.assertEqual(req.status, IORequestStatus.FAILED)
        self.assertEqual(req.error_message, "Erro de E/S: Bloco danificado")

    def test_queue_operations(self):
        queue = IOQueue(max_size=3)
        self.assertTrue(queue.is_empty())
        self.assertEqual(len(queue), 0)

        r1 = IORequest(operation=IOOperationType.READ, block_id=1, track=10)
        r2 = IORequest(operation=IOOperationType.READ, block_id=2, track=20)
        r3 = IORequest(operation=IOOperationType.READ, block_id=3, track=30)

        queue.enqueue(r1)
        queue.enqueue(r2)
        queue.enqueue(r3)
        self.assertEqual(len(queue), 3)

        # Overflow error
        r4 = IORequest(operation=IOOperationType.READ, block_id=4, track=40)
        with self.assertRaises(OverflowError):
            queue.enqueue(r4)

        # Peek
        self.assertEqual(queue.peek(), r1)

        # Dequeue
        dequeued = queue.dequeue()
        self.assertEqual(dequeued, r1)
        self.assertEqual(len(queue), 2)
        self.assertEqual(queue.peek(), r2)

        # Remove specific
        self.assertTrue(queue.remove(r3))
        self.assertEqual(len(queue), 1)
        self.assertFalse(queue.remove(r3))

        # Clear
        queue.clear()
        self.assertTrue(queue.is_empty())


if __name__ == "__main__":
    unittest.main()
