"""Validate requested flavor quantities independently of pricing and stock allocation."""


class FlavorAllocationError(ValueError):
    def __init__(self, message, field="catering_request.flavor_allocations"):
        super().__init__(message)
        self.field = field


def clean_flavor_allocations(value, total):
    if not isinstance(value, list) or len(value) > 5:
        raise FlavorAllocationError("Choose up to five flavors with quantities.")
    cleaned, names = [], set()
    for index, row in enumerate(value):
        path = f"catering_request.flavor_allocations[{index}]"
        if not isinstance(row, dict) or set(row) != {"flavor", "quantity"}:
            raise FlavorAllocationError("Each flavor needs a name and quantity.", path)
        name, quantity = row["flavor"], row["quantity"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise FlavorAllocationError(
                "Enter a flavor name of 1 to 100 characters.", path + ".flavor"
            )
        name = name.strip()
        if name.casefold() in names:
            raise FlavorAllocationError("Choose each flavor only once.", path + ".flavor")
        if type(quantity) is not int or not 1 <= quantity <= 100000:
            raise FlavorAllocationError(
                "Enter a whole-number flavor quantity from 1 to 100,000.", path + ".quantity"
            )
        names.add(name.casefold())
        cleaned.append({"flavor": name, "quantity": quantity})
    if cleaned and isinstance(total, (int, float)) and not isinstance(total, bool):
        if sum(row["quantity"] for row in cleaned) != total:
            raise FlavorAllocationError(
                "Flavor quantities must add up to the total paleta quantity."
            )
    return cleaned
