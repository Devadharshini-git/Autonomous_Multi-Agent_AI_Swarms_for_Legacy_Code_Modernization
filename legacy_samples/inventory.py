# legacy_samples/inventory.py
# Old-style Python 2 inventory management script

class InventoryItem:
    def __init__(self, name, quantity, price):
        self.name = name
        self.quantity = quantity
        self.price = price

    def total_value(self):
        return self.quantity * self.price

    def display(self):
        print "Item: %s, Qty: %d, Price: $%.2f" % (self.name, self.quantity, self.price)


def load_inventory():
    items = []
    items.append(InventoryItem("Widget", 100, 2.50))
    items.append(InventoryItem("Gadget", 50, 9.99))
    return items


def calculate_total(items):
    total = 0
    for i in xrange(len(items)):
        total += items[i].total_value()
    return total


def print_report(items):
    print "=== Inventory Report ==="
    for item in items:
        item.display()
    print "Total value: $%.2f" % calculate_total(items)


if __name__ == '__main__':
    inventory = load_inventory()
    print_report(inventory)