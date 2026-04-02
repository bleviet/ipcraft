from ipcraft.model.core import IpCore


def generate_ascii_diagram(ip_core: IpCore) -> str:
    """Generate an ASCII diagram of the IP Core symbol."""
    inputs = []
    outputs = []

    # Sort and collect clocks/resets
    for clk in ip_core.clocks:
        if clk.direction.value == "in":
            inputs.append(clk.name)
        else:
            outputs.append(clk.name)

    for rst in ip_core.resets:
        if rst.direction.value == "in":
            inputs.append(rst.name)
        else:
            outputs.append(rst.name)

    # Collect bus interfaces (logical grouping)
    for bus in ip_core.bus_interfaces:
        mode = bus.mode.value
        if mode in ["slave", "sink"]:
            inputs.append(f"[{bus.type}] {bus.name}")
        else:
            outputs.append(f"[{bus.type}] {bus.name}")

    # Collect other standard ports
    for port in ip_core.ports:
        direction = port.direction.value
        width_str = ""
        if isinstance(port.width, int) and port.width > 1:
            width_str = f"[{port.width-1}:0]"
        elif isinstance(port.width, str):
            width_str = f"[{port.width}-1:0]"

        port_label = f"{port.name} {width_str}".strip()

        if direction == "in":
            inputs.append(port_label)
        elif direction == "out":
            outputs.append(port_label)
        else:
            # inout -> put on output side with a special marker or just treat as output side for balance
            outputs.append(f"<-> {port_label}")

    title = ip_core.vlnv.name

    # Calculate box dimensions
    max_in_len = max([len(i) for i in inputs]) if inputs else 0
    max_out_len = max([len(o) for o in outputs]) if outputs else 0
    box_width = max(len(title) + 6, max_in_len + max_out_len + 10)

    lines = []
    lines.append(f"    +{'-' * box_width}+")

    # Center the title
    title_padding = (box_width - len(title)) // 2
    title_line = f"    |{' ' * title_padding}{title}{' ' * (box_width - len(title) - title_padding)}|"
    lines.append(title_line)
    lines.append(f"    |{'-' * box_width}|")

    max_ports = max(len(inputs), len(outputs))
    if max_ports == 0:
        lines.append(f"    |{' ' * box_width}|")

    for i in range(max_ports):
        left_port = inputs[i] if i < len(inputs) else ""
        right_port = outputs[i] if i < len(outputs) else ""

        left_str = f"--> | {left_port}" if left_port else f"    | "
        left_pad = max_in_len - len(left_port)
        left_str += " " * left_pad

        right_pad = max_out_len - len(right_port)
        # spaces between the end of left max and start of right max
        middle_pad = box_width - (max_in_len + max_out_len + 2)

        right_str = f"{' ' * middle_pad}{right_port}{' ' * right_pad} |"
        if right_port:
            right_str += " -->"

        lines.append(left_str + right_str)

    lines.append(f"    +{'-' * box_width}+")
    return "\n".join(lines)
